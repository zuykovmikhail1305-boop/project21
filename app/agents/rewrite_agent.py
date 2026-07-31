"""Rewrite Agent: рерайтинг поисковых результатов через GigaChat.

Преобразует набор чанков из RAG-поиска в связный структурированный ответ
на естественном языке с использованием GigaChat.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

try:
    from langchain_gigachat import GigaChat as GigaChatLangChain
except Exception:  # pragma: no cover - optional dependency guard
    GigaChatLangChain = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None

from app.core import config


logger = logging.getLogger(__name__)


class RewriteResponse(BaseModel):
    """Структурированный ответ после рерайтинга."""
    answer: str = Field(description="Связный ответ на вопрос пользователя на основе предоставленных фрагментов документов")
    citations: list[str] = Field(default_factory=list, description="Список источников (document_id)")

    model_config = {"extra": "forbid"}


REWRITE_SYSTEM_PROMPT = """Ты — ассистент, который помогает пользователю найти информацию в корпоративных документах.

Твоя задача — на основе предоставленных фрагментов документов составить связный, структурированный ответ на вопрос пользователя.

Правила:
1. Отвечай ТОЛЬКО на основе предоставленных фрагментов. Не используй свои знания.
2. Если фрагменты не содержат ответа на вопрос — так и скажи.
3. Если информация в фрагментах противоречива — укажи это.
4. Ссылайся на источники в формате [документ X, чанк Y].
5. Ответ должен быть на том же языке, что и вопрос пользователя.
6. Структурируй ответ: используй абзацы, списки, выделение ключевых фактов.
7. Не добавляй информацию, которой нет в фрагментах."""


class RewriteAgent:
    """Рерайтинг поисковых результатов через GigaChat."""

    def __init__(self):
        self._gigachat_chain = None
        self._openai_chain = None

        # 1. GigaChat (langchain-gigachat) — приоритет
        self._init_gigachat()

        # 2. ChatOpenAI — fallback
        self._init_openai()

    def _init_gigachat(self) -> None:
        """Инициализировать GigaChat через langchain-gigachat."""
        if GigaChatLangChain is None:
            return

        has_creds = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )
        if not has_creds:
            return

        try:
            llm = GigaChatLangChain(
                credentials=config.GIGACHAT_CREDENTIALS,
                scope=config.GIGACHAT_SCOPE,
                base_url=config.GIGACHAT_API_URL,
                auth_url=config.GIGACHAT_AUTH_URL,
                model=config.GIGACHAT_MODEL,
                temperature=0.1,
                verify_ssl_certs=False,
                timeout=30,
            )
            self._gigachat_chain = llm.with_structured_output(RewriteResponse)
        except Exception:
            self._gigachat_chain = None

    def _init_openai(self) -> None:
        """Инициализировать ChatOpenAI как fallback."""
        if ChatOpenAI is None:
            return

        try:
            llm = ChatOpenAI(
                model=config.OPENAI_MODEL,
                temperature=0.1,
                api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_API_BASE,
            )
            self._openai_chain = llm.with_structured_output(RewriteResponse)
        except Exception:
            self._openai_chain = None

    async def rewrite(
        self,
        query: str,
        context: str,
    ) -> RewriteResponse:
        """Переписать поисковые результаты в связный ответ.

        Args:
            query: Исходный вопрос пользователя.
            context: Форматированный контекст из найденных чанков (с источниками).

        Returns:
            RewriteResponse со связным ответом.
        """
        logger.info(
            "RewriteAgent.rewrite: query=%s, context_len=%d",
            query[:100], len(context),
        )

        # Если контекст пустой или содержит только сообщение "ничего не найдено"
        if not context or "ничего не найдено" in context.lower()[:100]:
            logger.warning("RewriteAgent: empty context, returning fallback")
            return RewriteResponse(
                answer="По вашему запросу ничего не найдено.",
                citations=[],
            )

        user_prompt = f"""Вопрос пользователя: {query}

Фрагменты документов:
{context}

Составь связный ответ на вопрос пользователя на основе предоставленных фрагментов."""

        # 1. GigaChat with_structured_output
        if self._gigachat_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=REWRITE_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ]
                result = await self._gigachat_chain.ainvoke(messages)
                if isinstance(result, RewriteResponse):
                    logger.info(
                        "RewriteAgent.rewrite result (GigaChat): answer_len=%d, n_citations=%d",
                        len(result.answer), len(result.citations),
                    )
                    return result
            except Exception as e:
                logger.warning("RewriteAgent: GigaChat failed: %s", e)

        # 2. ChatOpenAI with_structured_output
        if self._openai_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=REWRITE_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ]
                result = await self._openai_chain.ainvoke(messages)
                if isinstance(result, RewriteResponse):
                    logger.info(
                        "RewriteAgent.rewrite result (OpenAI): answer_len=%d, n_citations=%d",
                        len(result.answer), len(result.citations),
                    )
                    return result
            except Exception as e:
                logger.warning("RewriteAgent: OpenAI failed: %s", e)

        # 3. Fallback: возвращаем контекст как есть
        logger.warning("RewriteAgent: all LLM providers failed, returning raw context")
        return RewriteResponse(
            answer=context,
            citations=[],
        )