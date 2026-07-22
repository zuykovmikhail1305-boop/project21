"""Analytics & Tagging Agent: генерация тегов, выявление дубликатов, граф связей."""

from typing import Optional

try:
    from langchain_gigachat import GigaChat as GigaChatLangChain
except Exception:  # pragma: no cover - optional dependency guard
    GigaChatLangChain = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None

from pydantic import BaseModel, Field

from app.core import config


class AnalyticsResponse(BaseModel):
    """Структурированный ответ аналитического агента."""
    tags: list[str] = Field(description="Список тегов для документа")
    related_topics: list[str] = Field(description="Связанные темы")
    document_type: str = Field(description="Тип документа")
    complexity: str = Field(description="Сложность: low, medium, high")
    summary: str = Field(description="Краткое описание документа (2-3 предложения)")


ANALYTICS_SYSTEM_PROMPT = """Ты — аналитик корпоративных документов.
Проанализируй предоставленный текст документа и верни структурированный ответ.

Определи:
- tags: Ключевые теги документа (2-5 тегов, на русском)
- related_topics: Связанные темы (1-3 темы)
- document_type: Тип документа (article, report, presentation, technical_doc, business_doc, other)
- complexity: Сложность (low, medium, high)
- summary: Краткое описание документа (2-3 предложения на русском)"""


class AnalyticsAgent:
    """Агент для аналитики документов."""

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
            credentials = (
                f"{config.GIGACHAT_CLIENT_ID}|{config.GIGACHAT_CLIENT_SECRET}"
            )
            llm = GigaChatLangChain(
                credentials=credentials,
                scope=getattr(config, "GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                base_url=getattr(config, "GIGACHAT_API_URL", "https://gigachat.devices.sberbank.ru/api/v1"),
                auth_url=getattr(config, "GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"),
                model="GigaChat",
                temperature=0.1,
                verify_ssl_certs=False,
                timeout=30,
            )
            self._gigachat_chain = llm.with_structured_output(AnalyticsResponse)
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
            self._openai_chain = llm.with_structured_output(AnalyticsResponse)
        except Exception:
            self._openai_chain = None

    async def analyze(self, document_text: str) -> AnalyticsResponse:
        """Проанализировать документ с помощью LLM.

        Args:
            document_text: Текст документа для анализа.

        Returns:
            AnalyticsResponse с тегами, типом, сложностью и описанием.
        """
        max_chars = 100000
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        # 1. GigaChat with_structured_output
        if self._gigachat_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=ANALYTICS_SYSTEM_PROMPT),
                    HumanMessage(content=f"Проанализируй этот документ:\n\n{document_text}"),
                ]
                result = await self._gigachat_chain.ainvoke(messages)
                if isinstance(result, AnalyticsResponse):
                    return result
            except Exception:
                pass

        # 2. ChatOpenAI with_structured_output
        if self._openai_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=ANALYTICS_SYSTEM_PROMPT),
                    HumanMessage(content=f"Проанализируй этот документ:\n\n{document_text}"),
                ]
                result = await self._openai_chain.ainvoke(messages)
                if isinstance(result, AnalyticsResponse):
                    return result
            except Exception:
                pass

        # 3. Fallback — возвращаем базовый анализ
        return AnalyticsResponse(
            tags=["general"],
            related_topics=[],
            document_type="other",
            complexity="medium",
            summary=document_text[:500],
        )
