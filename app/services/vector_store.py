"""Сервис для работы с Qdrant: hybrid search, ACL-фильтрация."""

from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import QDRANT_COLLECTION_NAME
from app.core.dependencies import get_qdrant_client
from app.services.acl import build_qdrant_filter


class VectorStore:
    """Сервис для поиска по векторной БД Qdrant."""

    def __init__(self, client: Optional[QdrantClient] = None):
        self.client = client or get_qdrant_client()

    async def search(
        self,
        query_vector: list[float],
        user_groups: list[int],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
    ) -> list[dict]:
        """Поиск по вектору с ACL-фильтрацией.

        Args:
            query_vector: Вектор запроса.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов.
            score_threshold: Минимальный порог сходства.

        Returns:
            Список чанков с метаданными.
        """
        # Строим ACL-фильтр
        acl_filter = build_qdrant_filter(user_groups)

        # Поиск
        search_result = self.client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=models.Filter(**acl_filter),
            limit=top_k,
            score_threshold=score_threshold,
        )

        # Форматируем результат
        results = []
        for point in search_result:
            results.append({
                "id": point.id,
                "score": point.score,
                "content": point.payload.get("content", ""),
                "document_id": point.payload.get("document_id"),
                "chunk_index": point.payload.get("chunk_index"),
                "chunk_type": point.payload.get("chunk_type", "text"),
                "metadata": point.payload.get("metadata", {}),
            })

        return results

    async def hybrid_search(
        self,
        query_vector: list[float],
        user_groups: list[int],
        query_text: Optional[str] = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Гибридный поиск (векторный + keyword).

        Для MVP используем только векторный поиск.
        BM25 будет добавлен при интеграции с Qdrant 1.8+.
        """
        return await self.search(
            query_vector=query_vector,
            user_groups=user_groups,
            top_k=top_k,
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