"""Search & RAG Agent: поиск чанков через search endpoint, формирование ответа из них.

Использует ТОЛЬКО /rag/search endpoint. Ответ формируется напрямую из найденных чанков
без вызова LLM (без /rag/answer).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.rag_client import RAGClient


logger = logging.getLogger(__name__)


class SearchRAGAgent:
    """Поиск информации в документах через RAG API (только search endpoint).

    Вместо вызова /rag/answer использует только /rag/search и формирует ответ
    из содержимого найденных чанков.
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
        """Ответить на вопрос пользователя на основе документов.

        Использует ТОЛЬКО search endpoint. Ответ формируется из текста найденных чанков.
        Confidence вычисляется как средний rerank_score по чанкам.

        Returns:
            dict с ключами:
                - answer: сформированный ответ из чанков
                - chunks: список найденных чанков
                - citations: цитаты из чанков
                - confidence: средняя уверенность по чанкам (0.0..1.0)
        """
        logger.info(
            "SearchRAGAgent.answer: query=%s, user_groups=%s, history_len=%d",
            query[:100], user_groups, len(self._history),
        )

        # Используем ТОЛЬКО search endpoint
        chunks = await self.rag_client.search(
            query=query,
            user_groups=user_groups,
            history=self._history,
            top_k=20,
        )

        # Формируем ответ из чанков
        answer = self._build_answer_from_chunks(chunks)
        citations = self._build_citations(chunks)
        confidence = self._compute_confidence(chunks)

        # Обновляем историю
        self._history.append({"role": "user", "content": query})
        self._history.append({"role": "assistant", "content": answer})

        result = {
            "answer": answer,
            "chunks": chunks,
            "citations": citations,
            "confidence": confidence,
        }

        logger.info(
            "SearchRAGAgent.answer result: answer_len=%d, n_chunks=%d, confidence=%s",
            len(answer), len(chunks), confidence,
        )
        return result

    def _build_answer_from_chunks(self, chunks: list[dict]) -> str:
        """Сформировать ответ из текста найденных чанков."""
        if not chunks:
            return "По вашему запросу ничего не найдено."

        parts = []
        for i, chunk in enumerate(chunks[:10]):
            content = (chunk.get("text") or chunk.get("content") or "").strip()
            doc_id = chunk.get("document_id", "?")
            score = chunk.get("rerank_score", chunk.get("score", 0))
            if content:
                parts.append(
                    f"[{i + 1}] (документ {doc_id}, релевантность: {score:.2f})\n{content}"
                )

        if not parts:
            return "По вашему запросу ничего не найдено."

        return "\n\n".join(parts)

    def _build_citations(self, chunks: list[dict]) -> list[dict]:
        """Сформировать цитаты из метаданных чанков."""
        citations = []
        seen = set()
        for chunk in chunks:
            doc_id = chunk.get("document_id")
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                citations.append({
                    "document_id": doc_id,
                    "document_name": chunk.get("document_name", f"Документ {doc_id}"),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "score": chunk.get("rerank_score", chunk.get("score", 0)),
                })
        return citations

    def _compute_confidence(self, chunks: list[dict]) -> float:
        """Вычислить уверенность как средний rerank_score по чанкам."""
        if not chunks:
            return 0.0

        scores = [
            chunk.get("rerank_score", chunk.get("score", 0))
            for chunk in chunks
        ]
        # Берём среднее по топ-5 чанкам
        top_scores = scores[:5]
        if not top_scores:
            return 0.0

        confidence = sum(top_scores) / len(top_scores)
        # Нормализуем в [0, 1] если scores уже не в этом диапазоне
        if confidence > 1.0:
            confidence = min(confidence / 100.0, 1.0)
        return round(max(0.0, min(confidence, 1.0)), 4)
