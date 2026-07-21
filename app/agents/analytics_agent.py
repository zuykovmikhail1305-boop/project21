"""Analytics & Tagging Agent: генерация тегов, выявление дубликатов, граф связей."""

from typing import Optional

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


class AnalyticsAgent:
    """Агент для аналитики документов."""

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

    async def analyze(self, document_text: str) -> AnalyticsResponse:
        """Проанализировать документ."""
        max_chars = 100000
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        return AnalyticsResponse(
            tags=["general"],
            related_topics=[],
            document_type="other",
            complexity="medium",
            summary=document_text[:500],
        )
