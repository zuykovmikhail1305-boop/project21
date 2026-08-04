"""Vector Store - совместимая версия для старого кода (обёртка над rag_embedder.py)."""

from app.services.rag_embedder import Embedding

from qdrant_client import QdrantClient
from qdrant_client.http import models

try:
    from qdrant_client.http.exceptions import UnexpectedStatusCode
except ImportError:  # compatibility with older qdrant-client versions
    UnexpectedStatusCode = Exception

from app.core.config import QDRANT_COLLECTION_NAME, QDRANT_VECTOR_SIZE, SPARSE_SEARCH_ENABLED, SPARSE_VECTOR_NAME, QDRANT_BASE, QDRANT_COLLECTION
from app.core.dependencies import get_qdrant_client
from app.services.acl import build_qdrant_filter


class VectorStore:
    """Vector store for Qdrant - обёртка для обратной совместимости."""

    def __init__(self):
        self.embedding = Embedding()
        self.qdrant_url = QDRANT_BASE
        self.collection_name = QDRANT_COLLECTION

    def search(self, query: str, limit: int = 20, collection_name: str = None):
        """Поиск в векторном хранилище."""
        if collection_name is None:
            collection_name = self.collection_name

        results = self.embedding.dense_search(query, collection_name=collection_name, limit=limit)
        return results

    def save_vectors(self, data, collection_name: str = None):
        """Сохранить векторы в Qdrant.
        if collection_name is None:
            collection_name = self.collection_name

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
            vector_size = QDRANT_VECTOR_SIZE

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
