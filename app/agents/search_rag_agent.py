"""Search & RAG Agent: извлечение контекста из Qdrant, формирование промпта, вызов LLM."""

from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.services.vector_store import VectorStore
from app.services.reranker import Reranker
from app.services.embedder import EmbedderService
from app.core.dependencies import get_embedder
from app.core import config


class RAGResponse(BaseModel):
    """Структурированный ответ RAG агента."""
    answer: str = Field(description="Ответ на вопрос пользователя на основе контекста")
    confidence: float = Field(description="Уверенность в ответе от 0.0 до 1.0", ge=0.0, le=1.0)


SEARCH_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Ты — ассистент по корпоративным документам. Ответь на вопрос пользователя, "
        "используя ТОЛЬКО информацию из предоставленного контекста.\n\n"
        "Инструкции:\n"
        "1. Отвечай только на основе предоставленного контекста.\n"
        "2. Если в контексте нет информации для ответа, скажи: "
        '"Я не нашел информации по вашему вопросу в доступных документах."\n'
        "3. Ссылайся на источники в формате 'документ №X'.\n"
        "4. Ответ должен быть на русском языке.\n"
        "5. Будь краток и конкретен.\n\n"
        "Контекст из документов:\n{context}",
    ),
    ("human", "{query}"),
])


class SearchRAGAgent:
    """Поиск информации в документах и генерация ответа."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or Reranker()

        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL,
            temperature=0.1,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.chain = SEARCH_PROMPT | self.llm.with_structured_output(RAGResponse)

    async def search(self, query: str, user_groups: list[int]) -> list[dict]:
        """Поиск релевантных чанков."""
        query_vector = self.embedder.embed(query)

        results = await self.vector_store.search(
            query_vector=query_vector,
            user_groups=user_groups,
            top_k=20,
        )

        reranked = self.reranker.rerank(query, results, top_k=5)
        return reranked

    async def answer(self, query: str, user_groups: list[int]) -> dict:
        """Ответить на вопрос пользователя на основе документов."""
        chunks = await self.search(query, user_groups)

        if not chunks:
            return {
                "answer": "Я не нашел информации по вашему вопросу в доступных документах.",
                "citations": [],
                "chunks": [],
            }

        # Формируем контекст
        context_parts = []
        citations = []
        for i, chunk in enumerate(chunks):
            context_parts.append(
                f"[Источник: документ №{chunk['document_id']}, "
                f"чанк №{chunk['chunk_index']}]\n{chunk['content']}"
            )
            citations.append({
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
                "score": chunk.get("rerank_score", chunk.get("score", 0)),
            })

        context = "\n\n".join(context_parts)

        # Генерация структурированного ответа
        result = await self.chain.ainvoke({
            "context": context,
            "query": query,
        })

        return {
            "answer": result.answer,
            "confidence": result.confidence,
            "citations": citations,
            "chunks": chunks,
        }