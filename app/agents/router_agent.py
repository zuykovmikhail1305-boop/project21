"""Router Agent: семантический роутер с LangChain with_structured_output.

Стратегия (chain of responsibility):
1. GigaChat (langchain-gigachat) с with_structured_output — если есть GIGACHAT_CLIENT_ID/SECRET
2. ChatOpenAI (langchain-openai) с with_structured_output — если есть OPENAI_API_KEY/BASE
3. Keyword-matching fallback — всегда доступен
"""

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


# Системный промпт для семантической маршрутизации
ROUTER_SYSTEM_PROMPT = """Ты — семантический роутер для корпоративного ассистента по документам.
Определи, какой агент лучше всего подходит для обработки запроса пользователя.

Доступные маршруты:
- search: Поиск информации в документах. Используй, если пользователь задаёт вопрос, ищет факты, данные, ответы в документах.
- summarize: Саммари документа. Используй, если пользователь просит краткое содержание, summary, основные тезисы.
- analyze: Анализ документа. Используй, если пользователь просит анализ, оценку, классификацию.
- generate: Генерация артефакта (отчёт, презентация, PDF, дашборд).
- general: Общий разговор. Используй, если пользователь здоровается, прощается, задаёт общие вопросы.

Верни структурированный ответ с маршрутом, уверенностью (0.0-1.0) и кратким обоснованием."""


class RouterAgent:
    """Семантический роутер с LangChain with_structured_output.

    Стратегия маршрутизации (chain of responsibility):
    1. GigaChat (langchain-gigachat) с with_structured_output
       — использует OAuth client credentials (GIGACHAT_CLIENT_ID + GIGACHAT_CLIENT_SECRET)
       — нативно поддерживает Pydantic-схемы через with_structured_output
    2. ChatOpenAI (langchain-openai) с with_structured_output
       — для OpenAI-совместимых API (LM Studio, Ollama, OpenAI)
    3. Keyword-matching fallback — всегда доступен
    """

    def __init__(self):
        self._gigachat_chain = None
        self._openai_chain = None

        # 1. GigaChat (langchain-gigachat) — приоритетный LLM
        self._init_gigachat()

        # 2. ChatOpenAI — fallback, если GigaChat недоступен
        self._init_openai()

    def _init_gigachat(self) -> None:
        """Инициализировать GigaChat через langchain-gigachat с with_structured_output.

        GigaChat из langchain-gigachat поддерживает with_structured_output
        нативно (method='json_schema' или 'function_calling').
        Использует OAuth client credentials для аутентификации.
        """
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
                temperature=0.0,
                verify_ssl_certs=False,
                timeout=30,
            )
            self._gigachat_chain = llm.with_structured_output(RouteDecision)
        except Exception:
            self._gigachat_chain = None

    def _init_openai(self) -> None:
        """Инициализировать ChatOpenAI с with_structured_output как fallback."""
        if ChatOpenAI is None:
            return

        try:
            llm = ChatOpenAI(
                model=config.OPENAI_MODEL,
                temperature=0.0,
                api_key=config.OPENAI_API_KEY,  # type: ignore[arg-type]
                base_url=config.OPENAI_API_BASE,
            )
            self._openai_chain = llm.with_structured_output(RouteDecision)
        except Exception:
            self._openai_chain = None

    async def route(self, query: str) -> RouteDecision:
        """Определить маршрут для запроса пользователя.

        Стратегия (chain of responsibility):
        1. GigaChat (langchain-gigachat) с with_structured_output
        2. ChatOpenAI (langchain-openai) с with_structured_output
        3. Keyword-matching fallback

        Args:
            query: Запрос пользователя.

        Returns:
            RouteDecision с полями route, confidence, reasoning.
        """
        import logging
        logger = logging.getLogger(__name__)

        # 1. GigaChat with_structured_output
        if self._gigachat_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                    HumanMessage(content=query),
                ]
                result = await self._gigachat_chain.ainvoke(messages)
                if isinstance(result, RouteDecision):
                    logger.info("=== DIAG: Router used GigaChat: route=%s, confidence=%.2f", result.route, result.confidence)
                    return result
                logger.warning("=== DIAG: GigaChat returned non-RouteDecision: %s", type(result))
            except Exception as e:
                logger.warning("=== DIAG: GigaChat router failed: %s", e)

        # 2. ChatOpenAI with_structured_output
        if self._openai_chain is not None:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                    HumanMessage(content=query),
                ]
                result = await self._openai_chain.ainvoke(messages)
                if isinstance(result, RouteDecision):
                    logger.info("=== DIAG: Router used ChatOpenAI: route=%s, confidence=%.2f", result.route, result.confidence)
                    return result
                logger.warning("=== DIAG: ChatOpenAI returned non-RouteDecision: %s", type(result))
            except Exception as e:
                logger.warning("=== DIAG: ChatOpenAI router failed: %s", e)

        # 3. Keyword-matching fallback
        lowered = query.lower()
        logger.info("=== DIAG: Router using keyword fallback for query: %s", query[:100])
        if any(token in lowered for token in ["найти", "поиск", "документ",
               "файл", "вопрос", "что", "как", "где", "справка",
               "найди", "покажи", "расскажи", "информация"]):
            return RouteDecision(route="search", confidence=0.3,
                                 reasoning="Использован fallback-роутинг по ключевым словам")
        if any(token in lowered for token in ["саммари", "краткое", "summary",
               "резюме", "тезис", "главн"]):
            return RouteDecision(route="summarize", confidence=0.3,
                                 reasoning="Использован fallback-роутинг по ключевым словам")
        if any(token in lowered for token in ["анализ", "анализир", "оцен",
               "классифицир", "тип документа", "сложность"]):
            return RouteDecision(route="analyze", confidence=0.3,
                                 reasoning="Использован fallback-роутинг по ключевым словам")
        if any(token in lowered for token in ["создай", "сгенерир", "отчёт",
               "презентаци", "график", "диаграмм", "артефакт", "построй",
               "сформируй", "документ", "pdf", "отчет"]):
            return RouteDecision(route="generate", confidence=0.3,
                                 reasoning="Использован fallback-роутинг по ключевым словам")
        logger.warning("=== DIAG: Router keyword fallback defaulted to 'general' for query: %s", query[:100])
        return RouteDecision(route="general", confidence=0.3,
                             reasoning="Использован fallback-роутинг по ключевым словам")
