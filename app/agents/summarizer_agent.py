"""Summarizer Agent: сжатие больших объёмов текста."""

from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core import config


class SummaryResponse(BaseModel):
    """Структурированный ответ суммарайзера."""
    summary: str = Field(description="Краткое содержание документа")
    key_points: list[str] = Field(description="Ключевые тезисы документа")
    document_type: str = Field(description="Тип документа: report, instruction, presentation, other")


SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Ты — ассистент для саммари корпоративных документов. "
        "Составь краткое содержание документа.\n\n"
        "Инструкции:\n"
        "1. Выдели основные темы и выводы.\n"
        "2. Перечисли ключевые тезисы.\n"
        "3. Определи тип документа.\n"
        "4. Ответ должен быть на русском языке.\n\n"
        "Текст документа:\n{document_text}",
    ),
    ("human", "Составь саммари этого документа."),
])


class SummarizerAgent:
    """Агент для саммари документов."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL,
            temperature=0.1,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.chain = SUMMARIZE_PROMPT | self.llm.with_structured_output(SummaryResponse)

    async def summarize(self, document_text: str) -> SummaryResponse:
        """Составить саммари документа."""
        # Обрезаем текст, если он слишком длинный
        max_chars = 100000  # ~25K токенов
        if len(document_text) > max_chars:
            document_text = document_text[:max_chars] + "\n\n[Текст обрезан...]"

        result = await self.chain.ainvoke({"document_text": document_text})
        return result