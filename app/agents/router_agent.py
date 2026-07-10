"""Router Agent: семантический роутер с LangChain with_structured_output."""

from typing import Optional
from pydantic import BaseModel, Field

# from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core import config


class RouteDecision(BaseModel):
    """Структурированный ответ роутера."""
    route: str = Field(
        description="Маршрут: search, summarize, analyze, или general",
        pattern=r"^(search|summarize|analyze|general)$",
    )
    confidence: float = Field(
        description="Уверенность в решении от 0.0 до 1.0",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Краткое обоснование выбора маршрута",
    )


ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Ты — семантический роутер. Определи намерение пользователя и выбери маршрут.\n\n"
        "Возможные маршруты:\n"
        "- search: пользователь ищет конкретную информацию, факты, данные в документах\n"
        "- summarize: пользователь хочет получить краткое содержание или саммари документа\n"
        "- analyze: пользователь хочет аналитику, теги, связи, дубликаты\n"
        "- general: общий вопрос, приветствие, не связанное с документами",
    ),
    ("human", "{query}"),
])


class RouterAgent:
    """Семантический роутер с LangChain structured output."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL,
            temperature=0.0,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.chain = ROUTER_PROMPT | self.llm.with_structured_output(RouteDecision)

    async def route(self, query: str) -> RouteDecision:
        """Определить маршрут для запроса пользователя.

        Args:
            query: Запрос пользователя.

        Returns:
            RouteDecision с полями route, confidence, reasoning.
        """
        result = await self.chain.ainvoke({"query": query})
        return result