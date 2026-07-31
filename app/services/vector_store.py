"""Vector store service for Qdrant operations.

Асинхронная версия с AsyncQdrantClient.
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Batch,
    PointStruct,
    VectorParams,
    HnswConfigDiff,
    SparseVectorParams,
    SparseIndexParams,
    Filter,
    FieldCondition,
    MatchValue,
    HasIdCondition,
)

from app.core.config import QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION_NAME, QDRANT_VECTOR_SIZE

logger = logging.getLogger(__name__)


class AsyncVectorStore:
    """Асинхронный Vector Store для Qdrant."""

    def __init__(
        self,
        host: str = QDRANT_HOST,
        port: int = QDRANT_PORT,
        collection_name: str = QDRANT_COLLECTION_NAME,
        vector_size: int = QDRANT_VECTOR_SIZE,
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._client: AsyncQdrantClient | None = None

    async def _get_client(self) -> AsyncQdrantClient:
        """Get or create async Qdrant client."""
        if self._client is None:
            self._client = AsyncQdrantClient(host=self.host, port=self.port)
        return self._client

    async def ensure_collection(
        self,
        collection_name: str | None = None,
        vector_size: int | None = None,
    ) -> None:
        """Create collection if it doesn't exist."""
        client = await self._get_client()
        name = collection_name or self.collection_name
        size = vector_size or self.vector_size

        collections = await client.get_collections()
        exists = any(c.name == name for c in collections.collections)

        if not exists:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=size, distance="Cosine"),
                hnsw_config=HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                ),
            )
            logger.info(f"Created Qdrant collection: {name} (size={size})")

    async def upsert_points(
        self,
        points: list[PointStruct],
        collection_name: str | None = None,
        vector_size: int | None = None,
    ) -> None:
        """Upsert points into Qdrant collection."""
        client = await self._get_client()
        name = collection_name or self.collection_name
        size = vector_size or self.vector_size

        await self.ensure_collection(name, size)
        await client.upsert(collection_name=name, points=points)
        logger.info(f"Upserted {len(points)} points into {name}")

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        collection_name: str | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors."""
        client = await self._get_client()
        name = collection_name or self.collection_name

        search_params = {
            "collection_name": name,
            "query_vector": query_vector,
            "limit": limit,
        }
        if score_threshold is not None:
            search_params["score_threshold"] = score_threshold

        results = await client.search(**search_params)
        return [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload,
                "version": hit.version,
            }
            for hit in results
        ]

    async def delete_document_vectors(
        self,
        document_id: int,
        collection_name: str | None = None,
    ) -> None:
        """Delete all vectors for a document."""
        client = await self._get_client()
        name = collection_name or self.collection_name

        await client.delete(
            collection_name=name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
        )
        logger.info(f"Deleted vectors for document {document_id} from {name}")

    async def delete_points_by_id(
        self,
        point_ids: list[int],
        collection_name: str | None = None,
    ) -> None:
        """Delete specific points by IDs."""
        client = await self._get_client()
        name = collection_name or self.collection_name

        await client.delete(
            collection_name=name,
            points_selector=HasIdCondition(has_id=point_ids),
        )

    async def close(self) -> None:
        """Close the Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    @staticmethod
    def prepare_point(
        point_id: int,
        vector: list[float],
        payload: dict[str, Any],
    ) -> PointStruct:
        """Create a PointStruct for upsert."""
        return PointStruct(id=point_id, vector=vector, payload=payload)

    @staticmethod
    def prepare_batch(
        ids: list[int],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> Batch:
        """Create a Batch for efficient upsert."""
        return Batch(ids=ids, vectors=vectors, payloads=payloads)
