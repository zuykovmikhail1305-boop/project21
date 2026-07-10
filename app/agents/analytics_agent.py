"""Analytics & Tagging Agent: генерация тегов, выявление дубликатов, граф связей."""

from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core import config


class AnalyticsResponse(BaseModel):
    """Структурированный ответ аналитического агента."""
    tags: list[str] = Field(description="Список тегов для документа")
    related_topics: list[str] = Field(description="Связанные темы")
    document_type: str = Field(description="Тип документа")
    complexity: str = Field(description="Сложность: low, medium, high")
    summary: str = Field(description="Краткое описание документа (2-3 предложения)")


ANALYTICS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Ты — аналитический агент для корпоративных документов. "
        "Проанализируй документ и предоставь структурированную аналитику.\n\n"
        "Инструкции:\n"
        "1. Определи тематику и сгенерируй релевантные теги.\n"
        "2. Определи связанные темы.\n"
        "3. Оцени сложность документа.\n"
        "4. Ответ должен быть на русском языке.\n\n"
        "Текст документа:\n{document_text}",
    ),
    ("human", "Проанализируй этот документ."),
])


class AnalyticsAgent:
    """Агент для аналитики документов."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL,
            temperature=0.1,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.chain = ANALYTICS_PROMPT | self.llm.with_structured_output(AnalyticsResponse)

    async def analyze(self, document_text: str) -> AnalyticsResponse:
        """Проанализировать документ."""
        max_chars = 100000
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        result = await self.chain.ainvoke({"document_text": document_text})
        return result