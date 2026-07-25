"""Search & RAG Agent: извлечение контекста через RAG API, формирование промпта, вызов LLM."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.services.rag_client import RAGClient


logger = logging.getLogger(__name__)


class RAGResponse(BaseModel):
    """Структурированный ответ RAG агента."""
    answer: str = Field(description="Ответ на вопрос пользователя на основе контекста")
    confidence: float = Field(description="Уверенность в ответе от 0.0 до 1.0", ge=0.0, le=1.0)


class SearchRAGAgent:
    """Поиск информации в документах и генерация ответа через RAG API.

    Вместо прямого вызова GigaChatRAGService использует HTTP-клиент RAGClient,
    который отправляет запросы на /api/v1/rag/* эндпоинты.
    """

    def __init__(
        self,
        rag_client: Optional[RAGClient] = None,
        token: Optional[str] = None,
    ):
        self.rag_client = rag_client or RAGClient(token=token or "")
        # История диалога для HyDE (как в RAG_Misha/find.py:158-160)
        self._history: list[dict] = []

    async def search(self, query: str, user_groups: list[int]) -> list[dict]:
        """Поиск релевантных чанков с историей для HyDE через RAG API."""
        logger.info(
            "SearchRAGAgent.search: query=%s, user_groups=%s, history_len=%d",
            query[:100], user_groups, len(self._history),
        )
        return await self.rag_client.search(
            query=query,
            user_groups=user_groups,
            history=self._history,
            top_k=20,
        )

    async def answer(self, query: str, user_groups: list[int]) -> dict:
        """Ответить на вопрос пользователя на основе документов через RAG API.

        Передаёт историю диалога в HyDE и обновляет её после ответа.
        """
        logger.info(
            "SearchRAGAgent.answer: query=%s, user_groups=%s, history_len=%d",
            query[:100], user_groups, len(self._history),
        )
        result = await self.rag_client.answer(
            query=query,
            user_groups=user_groups,
            history=self._history,
            top_k=5,
        )
        # Обновляем историю (как в RAG_Misha/find.py:158-160)
        self._history.append({"role": "user", "content": query})
        self._history.append({"role": "assistant", "content": result.get("answer", "")})
        logger.info(
            "SearchRAGAgent.answer result: answer_len=%d, n_chunks=%d, confidence=%s",
            len(result.get("answer", "")), len(result.get("chunks", [])), result.get("confidence"),
        )
        return result
