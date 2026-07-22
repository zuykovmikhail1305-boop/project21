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
        # История диалога для HyDE (как в RAG_Misha/find.py:158-160)
        self._history: list[dict] = []

    async def search(self, query: str, user_groups: list[int]) -> list[dict]:
        """Поиск релевантных чанков с историей для HyDE."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("=== DIAG: SearchRAGAgent.search: query=%s, user_groups=%s, history_len=%d",
                    query[:100], user_groups, len(self._history))
        return await self.rag_service.search(
            query=query,
            user_groups=user_groups,
            history=self._history,
            top_k=20,
        )

    async def answer(self, query: str, user_groups: list[int]) -> dict:
        """Ответить на вопрос пользователя на основе документов.

        Передаёт историю диалога в HyDE и обновляет её после ответа.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info("=== DIAG: SearchRAGAgent.answer: query=%s, user_groups=%s, history_len=%d",
                    query[:100], user_groups, len(self._history))
        result = await self.rag_service.answer(
            query=query,
            user_groups=user_groups,
            history=self._history,
            top_k=5,
        )
        # Обновляем историю (как в RAG_Misha/find.py:158-160)
        self._history.append({"role": "user", "content": query})
        self._history.append({"role": "assistant", "content": result.get("answer", "")})
        logger.info("=== DIAG: SearchRAGAgent.answer result: answer_len=%d, n_chunks=%d, confidence=%s",
                    len(result.get("answer", "")), len(result.get("chunks", [])), result.get("confidence"))
        return result
