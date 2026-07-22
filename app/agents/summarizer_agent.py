"""Summarizer Agent: сжатие больших объёмов текста через LLM."""

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


class SummaryResponse(BaseModel):
    """Структурированный ответ суммарайзера."""
    summary: str = Field(description="Краткое содержание документа")
    key_points: list[str] = Field(description="Ключевые тезисы документа")
    document_type: str = Field(description="Тип документа: report, instruction, presentation, other")


SUMMARIZER_SYSTEM_PROMPT = """Ты — ассистент для саммари документов.
Составь краткое содержание документа на русском языке.

Верни структурированный ответ:
- summary: Краткое содержание (3-5 предложений)
- key_points: Ключевые тезисы (3-7 пунктов)
- document_type: Тип документа (report, instruction, presentation, other)"""


class SummarizerAgent:
    """Агент для саммари документов через LLM."""

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
            self._gigachat_chain = llm.with_structured_output(SummaryResponse)
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
            self._openai_chain = llm.with_structured_output(SummaryResponse)
        except Exception:
            self._openai_chain = None

    async def summarize(self, document_text: str) -> SummaryResponse:
        """Составить саммари документа через LLM.

        Args:
            document_text: Текст документа для саммари.

        Returns:
            SummaryResponse с саммари, ключевыми тезисами и типом документа.
        """
        # Обрезаем текст, если он слишком длинный
        max_chars = 100000  # ~25K токенов
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        # 1. GigaChat with_structured_output
        if self._gigachat_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=SUMMARIZER_SYSTEM_PROMPT),
                    HumanMessage(content=f"Составь саммари этого документа:\n\n{document_text}"),
                ]
                result = await self._gigachat_chain.ainvoke(messages)
                if isinstance(result, SummaryResponse):
                    return result
            except Exception:
                pass

        # 2. ChatOpenAI with_structured_output
        if self._openai_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=SUMMARIZER_SYSTEM_PROMPT),
                    HumanMessage(content=f"Составь саммари этого документа:\n\n{document_text}"),
                ]
                result = await self._openai_chain.ainvoke(messages)
                if isinstance(result, SummaryResponse):
                    return result
            except Exception:
                pass

        # 3. Fallback
        return SummaryResponse(
            summary=document_text[:500],
            key_points=["Краткое содержание недоступно без LLM-провайдера"],
            document_type="other",
        )
