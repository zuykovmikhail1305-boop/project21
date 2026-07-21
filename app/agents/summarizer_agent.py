"""Summarizer Agent: сжатие больших объёмов текста."""

from typing import Optional

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


class SummarizerAgent:
    """Агент для саммари документов."""

    def __init__(self):
        self.llm = None
        self.chain = None

        if ChatOpenAI is not None:
            try:
                self.llm = ChatOpenAI(
                    model=config.OPENAI_MODEL,
                    temperature=0.1,
                    api_key=config.OPENAI_API_KEY,
                    base_url=config.OPENAI_API_BASE,
                )
            except Exception:
                self.llm = None

    async def summarize(self, document_text: str) -> SummaryResponse:
        """Составить саммари документа."""
        # Обрезаем текст, если он слишком длинный
        max_chars = 100000  # ~25K токенов
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        if self.llm is None:
            return SummaryResponse(
                summary=document_text[:500],
                key_points=["Краткое содержание недоступно без LLM-провайдера"],
                document_type="other",
            )

        return SummaryResponse(summary=document_text[:500], key_points=[], document_type="other")
