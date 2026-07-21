"""Router Agent: семантический роутер с LangChain with_structured_output."""

from typing import Optional
from pydantic import BaseModel, Field

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None

from app.core import config


class RouteDecision(BaseModel):
    """Структурированный ответ роутера."""
    route: str = Field(
        description="Маршрут: search, summarize, analyze, generate, или general",
        pattern=r"^(search|summarize|analyze|generate|general)$",
    )
    confidence: float = Field(
        description="Уверенность в решении от 0.0 до 1.0",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Краткое обоснование выбора маршрута",
    )


class RouterAgent:
    """Семантический роутер с LangChain structured output."""

    def __init__(self):
        self.llm = None
        self.chain = None

        if ChatOpenAI is not None:
            try:
                self.llm = ChatOpenAI(
                    model=config.OPENAI_MODEL,
                    temperature=0.0,
                    api_key=config.OPENAI_API_KEY,  # type: ignore[arg-type]
                    base_url=config.OPENAI_API_BASE,
                )
            except Exception:
                self.llm = None

    async def route(self, query: str) -> RouteDecision:
        """Определить маршрут для запроса пользователя.

        Args:
            query: Запрос пользователя.

        Returns:
            RouteDecision с полями route, confidence, reasoning.
        """
        lowered = query.lower()
        if any(token in lowered for token in ["найти", "поиск", "документ",
               "файл", "вопрос", "что", "как", "где", "справка"]):
            return RouteDecision(route="search", confidence=0.3,
                                 reasoning="Использован fallback-роутинг по ключевым словам")
        return RouteDecision(route="general", confidence=0.3,
                             reasoning="Использован fallback-роутинг по ключевым словам")
