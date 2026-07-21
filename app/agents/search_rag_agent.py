"""Search & RAG Agent: извлечение контекста из Qdrant, формирование промпта, вызов LLM."""

from typing import Optional

from pydantic import BaseModel, Field

from app.services.vector_store import VectorStore
from app.services.reranker import Reranker
from app.services.embedder import EmbedderService
from app.services.rag_service import GigaChatRAGService
from app.core.dependencies import get_embedder


class RAGResponse(BaseModel):
    """Структурированный ответ RAG агента."""
    answer: str = Field(description="Ответ на вопрос пользователя на основе контекста")
    confidence: float = Field(description="Уверенность в ответе от 0.0 до 1.0", ge=0.0, le=1.0)


class SearchRAGAgent:
    """Поиск информации в документах и генерация ответа."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
        rag_service: Optional[GigaChatRAGService] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or Reranker()
        self.rag_service = rag_service or GigaChatRAGService(
            vector_store=self.vector_store,
            embedder=self.embedder,
            reranker=self.reranker,
        )

    async def search(self, query: str, user_groups: list[int]) -> list[dict]:
        """Поиск релевантных чанков."""
        return self.rag_service.search(
            query=query,
            user_groups=user_groups,
            top_k=20,
        )

    async def answer(self, query: str, user_groups: list[int]) -> dict:
        """Ответить на вопрос пользователя на основе документов."""
        return self.rag_service.answer(
            query=query,
            user_groups=user_groups,
            top_k=5,
        )
