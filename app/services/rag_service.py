"""Новый сервис, который сохраняет идею RAG_Misha: parsing → chunking → HYDE → search → answer."""

from __future__ import annotations

import uuid
from typing import Optional

from app.core import config
from app.services.embedder import EmbedderService
from app.services.gigachat_provider import GigaChatClient
from app.services.reranker import Reranker
from app.services.vector_store import VectorStore


class GigaChatRAGService:
    """RAG-пайплайн, сохраняющий идею RAG_Misha и использующий GigaChat."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedder = embedder or EmbedderService()
        self.reranker = reranker or Reranker()
        self.llm = GigaChatClient()
        self._use_gigachat = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )

    def _build_hyde_prompt(self, query: str, history: Optional[list[dict]] = None) -> str:
        history_text = ""
        if history:
            history_text = "\n".join(
                f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history
            )

        return f"""Ты — генератор гипотетических документов для поиска (HyDE).
Твоя задача — по запросу пользователя создать короткий, связный текст, который выглядит как фрагмент реального документа, содержащего ответ на этот запрос.

История диалога:
{history_text}

Текущий запрос пользователя: {query}

Сгенерируй один короткий гипотетический документ, который помогает найти релевантные фрагменты в базе знаний.
Выведи только текст документа без пояснений."""

    def generate_hyde(self, query: str, history: Optional[list[dict]] = None) -> str:
        if not self._use_gigachat:
            return f"Гипотетический документ для запроса: {query}"

        prompt = self._build_hyde_prompt(query, history)
        return self.llm.generate_sync(prompt=prompt, system_prompt="Ты генерируешь гипотетический документ для поиска.")

    def search(self, query: str, user_groups: list[int], top_k: int = 20) -> list[dict]:
        """Поиск релевантных чанков по запросу и HyDE."""
        query_vector = self.embedder.embed(query)
        results = []

        try:
            results = self._search_with_vector_store(query_vector, user_groups, top_k=top_k)
        except Exception:
            results = []

        if not results:
            hyde_text = self.generate_hyde(query)
            hyde_vector = self.embedder.embed(hyde_text)
            results = self._search_with_vector_store(hyde_vector, user_groups, top_k=top_k)

        return self.reranker.rerank(query, results, top_k=5)

    def index_document(self, file_path: str, user_groups: Optional[list[int]] = None) -> list[dict]:
        """Проиндексировать документ по логике RAG_Misha: parsing → chunking → embed → Qdrant."""
        from RAG_Misha.processing import Processing

        processor = Processing(file_path)
        nodes = processor.chunking()

        if not nodes:
            return []

        points = []
        for index, node in enumerate(nodes):
            chunk_text = getattr(node, "text", None)
            if not chunk_text:
                continue

            embedding = self.embedder.embed(chunk_text)
            point_id = str(uuid.uuid4())
            payload = {
                "content": chunk_text,
                "document_id": file_path,
                "chunk_index": index,
                "chunk_type": "text",
                "metadata": getattr(node, "metadata", {}),
            }
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": payload,
            })

        if points:
            self.vector_store.upsert_points(
                points=points,
                vector_size=len(points[0]["vector"]),
            )

        return points

    def _search_with_vector_store(
        self,
        query_vector: list[float],
        user_groups: list[int],
        top_k: int = 20,
    ) -> list[dict]:
        import asyncio

        async def _do_search() -> list[dict]:
            return await self.vector_store.search(
                query_vector=query_vector,
                user_groups=user_groups,
                top_k=top_k,
            )

        try:
            return asyncio.run(_do_search())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_do_search())
            finally:
                loop.close()

    def answer(self, query: str, user_groups: list[int], top_k: int = 5) -> dict:
        """Сформировать ответ на основании найденных чанков."""
        chunks = self.search(query, user_groups, top_k=top_k)
        if not chunks:
            return {
                "answer": "Я не нашел информации по вашему вопросу в доступных документах.",
                "confidence": 0.0,
                "citations": [],
                "chunks": [],
            }

        context_parts = []
        citations = []
        for chunk in chunks:
            context_parts.append(
                f"[Источник: документ №{
                    chunk.get('document_id')}, чанк №{
                    chunk.get('chunk_index')}]\n{
                    chunk.get(
                        'content', '')}"
            )
            citations.append({
                "document_id": chunk.get("document_id"),
                "chunk_index": chunk.get("chunk_index"),
                "score": chunk.get("rerank_score", chunk.get("score", 0)),
            })

        context = "\n\n".join(context_parts)
        if not self._use_gigachat:
            answer = (
                f"На основании найденного контекста: \n\n{context[:1500]}"
            )
        else:
            answer = self.llm.generate_sync(
                prompt=query,
                system_prompt=(
                    "Ты — ассистент по корпоративным документам. "
                    "Отвечай только на основе предоставленного контекста. "
                    "Если информации недостаточно, честно скажи об этом.\n\n"
                    f"Контекст:\n{context}"
                ),
            )

        return {
            "answer": answer,
            "confidence": 0.9,
            "citations": citations,
            "chunks": chunks,
        }
