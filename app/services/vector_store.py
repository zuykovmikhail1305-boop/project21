"""Сервис для работы с Qdrant: hybrid search (dense + sparse), ACL-фильтрация и индексирование чанков."""

import re
from collections import Counter
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

try:
    from qdrant_client.http.exceptions import UnexpectedStatusCode
except ImportError:  # compatibility with older qdrant-client versions
    UnexpectedStatusCode = Exception

from app.core.config import QDRANT_COLLECTION_NAME, SPARSE_SEARCH_ENABLED, SPARSE_VECTOR_NAME
from app.core.dependencies import get_qdrant_client
from app.services.acl import build_qdrant_filter


class VectorStore:
    """Сервис для поиска по векторной БД Qdrant.

    Поддерживает:
    - Dense vector search (семантический поиск)
    - Sparse vector search (BM25-подобный keyword search)
    - ACL-фильтрация через allowed_groups
    """

    def __init__(self, client: Optional[QdrantClient] = None):
        self.client = client or get_qdrant_client()

    @staticmethod
    def _text_to_sparse_vector(text: str) -> Optional[models.SparseVector]:
        """Преобразовать текст в Qdrant SparseVector (term frequency).

        Использует BM25-подобную токенизацию из RAG_Misha/bm25_search.py.
        Токены хэшируются в индексное пространство для Qdrant sparse vector формата.

        Returns:
            models.SparseVector с indices и values, или None если текст пуст.
        """
        if not text or not text.strip():
            return None

        # Токенизация (как в RAG_Misha/bm25_search.py)
        tokens = re.findall(r'\w+', text.lower())
        if not tokens:
            return None

        term_freq = Counter(tokens)

        indices = []
        values = []
        # Хэшируем каждый терм в индекс в диапазоне [0, 10_000_000)
        # Это даёт достаточно большое sparse пространство
        for term, freq in term_freq.items():
            idx = abs(hash(term)) % 10_000_000
            indices.append(idx)
            # Используем log(1 + freq) для сглаживания (BM25-like)
            import math
            values.append(math.log1p(float(freq)))

        return models.SparseVector(
            indices=indices,
            values=values,
        )

    async def search(
        self,
        query_vector: list[float],
        user_groups: list[int],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> list[dict]:
        """Поиск по dense вектору с ACL-фильтрацией.

        Args:
            query_vector: Вектор запроса.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов.
            score_threshold: Минимальный порог сходства.

        Returns:
            Список чанков с метаданными.
        """
        import logging
        logger = logging.getLogger(__name__)

        # Строим ACL-фильтр
        acl_filter = build_qdrant_filter(user_groups)

        logger.info("=== DIAG: Qdrant search: collection=%s, top_k=%d, user_groups=%s, score_threshold=%s",
                    QDRANT_COLLECTION_NAME, top_k, user_groups, score_threshold)

        # Поиск через query_points (qdrant-client v1.18+)
        search_result = self.client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            query=query_vector,
            query_filter=models.Filter(**acl_filter),
            limit=top_k,
            score_threshold=score_threshold,
        )

        # Форматируем результат
        results = []
        for point in search_result.points:
            results.append(self._format_point(point))

        logger.info("=== DIAG: Qdrant search returned %d points (requested top_k=%d)", len(results), top_k)
        if results:
            logger.info("=== DIAG: First result: id=%s, score=%.4f, doc_id=%s, content_preview=%s",
                        results[0]["id"], results[0]["score"], results[0]["document_id"],
                        results[0]["content"][:100])
        else:
            logger.warning("=== DIAG: Qdrant search returned 0 points!")

        return results

    async def hybrid_search(
        self,
        query_vector: list[float],
        user_groups: list[int],
        query_text: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Гибридный поиск: dense + sparse vectors через Qdrant prefetch.

        Использует Qdrant prefetch для параллельного поиска по dense и sparse векторам.
        Результаты объединяются и ранжируются Qdrant'ом.

        Args:
            query_vector: Dense вектор запроса (из эмбеддера).
            user_groups: Список ID групп пользователя (для ACL).
            query_text: Исходный текст запроса для sparse поиска.
            top_k: Количество результатов.

        Returns:
            Список чанков с метаданными, отсортированный по релевантности.
        """
        import logging
        logger = logging.getLogger(__name__)

        acl_filter = build_qdrant_filter(user_groups)

        logger.info("=== DIAG: Qdrant hybrid_search: collection=%s, top_k=%d, user_groups=%s, sparse=%s, query_text=%s",
                    QDRANT_COLLECTION_NAME, top_k, user_groups, SPARSE_SEARCH_ENABLED, query_text[:100] if query_text else None)

        if query_text and SPARSE_SEARCH_ENABLED:
            sparse_vector = self._text_to_sparse_vector(query_text)
            logger.info("=== DIAG: Sparse vector generated: %d non-zero indices", len(sparse_vector.indices) if sparse_vector else 0)
            # Используем prefetch для параллельного dense + sparse поиска
            # NOTE: with_vector is NOT supported in all qdrant-client versions — removed to avoid API errors
            search_result = self.client.query_points(
                collection_name=QDRANT_COLLECTION_NAME,
                query=query_vector,
                query_filter=models.Filter(**acl_filter),
                limit=top_k,
                with_payload=True,
                prefetch=[
                    models.Prefetch(
                        query=sparse_vector,
                        using=SPARSE_VECTOR_NAME,  # имя sparse vector config
                        limit=top_k * 2,
                    )
                ],
            )
        else:
            logger.info("=== DIAG: hybrid_search fallback to dense-only (query_text=%s, SPARSE_SEARCH_ENABLED=%s)",
                        bool(query_text), SPARSE_SEARCH_ENABLED)
            # Fallback: только dense поиск
            search_result = self.client.query_points(
                collection_name=QDRANT_COLLECTION_NAME,
                query=query_vector,
                query_filter=models.Filter(**acl_filter),
                limit=top_k,
            )

        # Форматируем результат
        results = []
        for point in search_result.points:
            results.append(self._format_point(point))

        logger.info("=== DIAG: hybrid_search returned %d points", len(results))
        if results:
            logger.info("=== DIAG: First hybrid result: id=%s, score=%.4f, doc_id=%s",
                        results[0]["id"], results[0]["score"], results[0]["document_id"])
        else:
            logger.warning("=== DIAG: hybrid_search returned 0 points!")

        return results

    def upsert_points(
        self,
        points: list[dict],
        collection_name: Optional[str] = None,
        vector_size: Optional[int] = None,
    ) -> None:
        """Добавить точки в Qdrant с dense + sparse векторами.

        Для каждой точки автоматически генерирует sparse vector из текста (content).

        Args:
            points: Список точек с ключами 'id', 'vector', 'payload'.
            collection_name: Имя коллекции (по умолчанию из config).
            vector_size: Размерность dense вектора (по умолчанию 384).
        """
        collection_name = collection_name or QDRANT_COLLECTION_NAME
        self._ensure_collection(collection_name=collection_name, vector_size=vector_size)

        qdrant_points = []
        for point in points:
            # Генерируем sparse vector из текста чанка
            content = point["payload"].get("content", "")
            sparse_vector = self._text_to_sparse_vector(content)

            # Собираем векторную часть: dense + sparse
            vector_config: dict = {
                "": point["vector"],  # dense vector (default name)
            }
            if SPARSE_SEARCH_ENABLED and sparse_vector is not None and sparse_vector.indices:
                vector_config[SPARSE_VECTOR_NAME] = sparse_vector

            qdrant_points.append(
                models.PointStruct(
                    id=point["id"],
                    vector=vector_config,
                    payload=point["payload"],
                )
            )

        self.client.upsert(
            collection_name=collection_name,
            wait=True,
            points=qdrant_points,
        )

    def _ensure_collection(
        self,
        collection_name: Optional[str] = None,
        vector_size: Optional[int] = None,
    ) -> None:
        """Создать коллекцию с поддержкой dense + sparse vectors, если её нет.

        Sparse vectors используются для BM25-подобного keyword search.
        """
        collection_name = collection_name or QDRANT_COLLECTION_NAME
        if vector_size is None:
            vector_size = 384

        try:
            self.client.get_collection(collection_name=collection_name)
        except UnexpectedStatusCode:
            vectors_config: dict = {
                "": models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            }
            sparse_vectors_config: Optional[dict] = None
            if SPARSE_SEARCH_ENABLED:
                sparse_vectors_config = {
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        modifier=models.Modifier.IDF,  # BM25-like weighting
                    ),
                }

            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_vectors_config,
            )

    async def delete_document_vectors(self, document_id: int) -> None:
        """Удалить все векторы документа из Qdrant."""
        self.client.delete(
            collection_name=QDRANT_COLLECTION_NAME,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    ),
                ],
            ),
        )

    @staticmethod
    def _format_point(point) -> dict:
        """Форматировать точку Qdrant в единый dict для приложения."""
        return {
            "id": point.id,
            "score": point.score,
            "content": point.payload.get("content", ""),
            "document_id": point.payload.get("document_id"),
            "chunk_index": point.payload.get("chunk_index"),
            "chunk_type": point.payload.get("chunk_type", "text"),
            "metadata": point.payload.get("metadata", {}),
        }
