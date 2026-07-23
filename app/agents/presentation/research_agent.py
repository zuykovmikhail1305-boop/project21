"""Research Agent — собирает контекст из документов через SearchRAGAgent.

Оборачивает существующий SearchRAGAgent и добавляет LLM-извлечение
структурированных данных (key_facts, statistics) из найденного контекста.

Вход: query + user_groups
Выход: ResearchResult (summary, key_facts, statistics, has_sufficient_data, data_gaps)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.agents.presentation.base import BasePresentationAgent
from app.agents.presentation.models import ResearchResult
from app.agents.search_rag_agent import SearchRAGAgent
from app.services.vector_store import VectorStore
from app.services.reranker import Reranker
from app.services.embedder import EmbedderService
from app.core.dependencies import get_embedder

logger = logging.getLogger(__name__)

RESEARCH_EXTRACT_PROMPT = """Ты — аналитик данных. Твоя задача — извлечь структурированную информацию из контекста документов для создания презентации.

## Запрос пользователя
{query}

## Контекст из документов
{context}

## Что нужно извлечь
1. **summary** — краткое саммари (2-3 предложения) того, о чём контекст
2. **key_facts** — список ключевых фактов (каждый факт одним предложением)
3. **statistics** — числовые данные в формате: [{{"metric": "название метрики", "value": "значение", "period": "период", "source": "источник"}}]
4. **has_sufficient_data** — достаточно ли данных для создания полноценной презентации (true/false)
5. **data_gaps** — если данных недостаточно, чего именно не хватает
6. **suggested_queries** — 2-3 уточнённых запроса для повторного поиска (если данных мало)

## Пример
Контекст: "Выручка Ozon за 2024 год составила 500 млрд руб. Рост год к году — 30%."
Ответ:
- summary: "Ozon показал значительный рост выручки в 2024 году"
- key_facts: ["Выручка Ozon за 2024 год составила 500 млрд руб.", "Рост выручки год к году — 30%"]
- statistics: [{{"metric": "Выручка", "value": "500 млрд руб.", "period": "2024", "source": "контекст"}}]
- has_sufficient_data: true
- data_gaps: []
- suggested_queries: []
"""


class ResearchAgent(BasePresentationAgent):
    """Агент для сбора и структурирования контекста из документов.

    1. Вызывает SearchRAGAgent.answer() для поиска по документам
    2. Извлекает структурированные данные (key_facts, statistics) через LLM
    3. Определяет, достаточно ли данных для презентации
    """

    def __init__(
        self,
        search_rag: Optional[SearchRAGAgent] = None,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
    ) -> None:
        super().__init__()
        self.search_rag = search_rag or SearchRAGAgent(
            vector_store=vector_store or VectorStore(),
            embedder=embedder or get_embedder(),
            reranker=reranker or Reranker(),
        )
        self._extract_chain = self._build_text_chain(RESEARCH_EXTRACT_PROMPT)

    async def research(
        self,
        query: str,
        user_groups: list[int],
        intent_topics: Optional[list[str]] = None,
    ) -> ResearchResult:
        """Выполнить исследование по запросу.

        Args:
            query: Запрос пользователя.
            user_groups: Группы пользователя для фильтрации документов.
            intent_topics: Ключевые темы из IntentAgent (для уточнения поиска).

        Returns:
            ResearchResult со структурированными данными.
        """
        # 1. Поиск по документам
        try:
            logger.info("ResearchAgent: searching for query='%s'", query[:100])
            search_result = await self.search_rag.answer(
                query=query,
                user_groups=user_groups,
            )
        except Exception as e:
            logger.error("ResearchAgent: search failed: %s", e)
            return ResearchResult(
                summary="Поиск не удался",
                has_sufficient_data=False,
                data_gaps=[f"Ошибка поиска: {e}"],
            )

        # 2. Извлекаем контекст из результата поиска
        context = self._format_search_context(search_result)

        if not context:
            logger.warning("ResearchAgent: no context found")
            return ResearchResult(
                summary="Не найдено релевантных документов",
                has_sufficient_data=False,
                data_gaps=["Нет документов по запросу"],
                suggested_queries=[query],
            )

        # 3. Извлекаем структурированные данные через LLM
        if self._extract_chain is not None:
            try:
                raw_result = await self._extract_chain.ainvoke({
                    "query": query,
                    "context": context,
                })
                result = self._parse_llm_result(raw_result, context)
                logger.info(
                    "ResearchAgent: extracted %d facts, %d stats, sufficient=%s",
                    len(result.key_facts),
                    len(result.statistics),
                    result.has_sufficient_data,
                )
                return result
            except Exception as e:
                logger.error("ResearchAgent: LLM extraction failed: %s", e)

        # 4. Fallback: возвращаем сырой контекст
        return ResearchResult(
            summary=context[:500],
            has_sufficient_data=True,
        )

    def _format_search_context(self, search_result: dict[str, Any]) -> str:
        """Форматировать результат поиска в текст для LLM."""
        parts = []

        # Answer от RAG
        answer = search_result.get("answer", "")
        if answer:
            parts.append(f"## Ответ\n{answer}")

        # Чанки
        chunks = search_result.get("chunks", [])
        if chunks:
            chunk_texts = []
            for i, chunk in enumerate(chunks[:10]):
                content = chunk.get("content", "")
                doc_id = chunk.get("document_id", "?")
                score = chunk.get("rerank_score", chunk.get("score", 0))
                if content:
                    chunk_texts.append(
                        f"[Чанк {i+1}] (документ {doc_id}, релевантность: {score:.2f})\n{content}"
                    )
            if chunk_texts:
                parts.append("## Чанки\n" + "\n\n".join(chunk_texts))

        return "\n\n".join(parts)

    def _parse_llm_result(self, raw: str, context: str) -> ResearchResult:
        """Парсить JSON-ответ от LLM в ResearchResult."""
        # Пробуем извлечь JSON из ответа
        json_str = raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
            return ResearchResult(
                summary=data.get("summary", context[:500]),
                key_facts=data.get("key_facts", []),
                statistics=data.get("statistics", []),
                has_sufficient_data=data.get("has_sufficient_data", True),
                data_gaps=data.get("data_gaps", []),
                suggested_queries=data.get("suggested_queries", []),
            )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("ResearchAgent: failed to parse LLM JSON: %s", e)
            return ResearchResult(
                summary=context[:500],
                has_sufficient_data=True,
            )