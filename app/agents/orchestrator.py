"""LangGraph оркестратор: Router → Search/RAG → Summarizer/Analytics."""

from typing import TypedDict, Literal, Optional
from langgraph.graph import StateGraph, END

from app.agents.router_agent import RouterAgent, RouteDecision
from app.agents.search_rag_agent import SearchRAGAgent
from app.agents.summarizer_agent import SummarizerAgent
from app.agents.analytics_agent import AnalyticsAgent


class AgentState(TypedDict):
    """Состояние агента в LangGraph графе."""
    query: str
    user_id: int
    user_groups: list[int]
    route: Optional[str]
    route_decision: Optional[RouteDecision]
    search_result: Optional[dict]
    summary_result: Optional[dict]
    analytics_result: Optional[dict]
    final_answer: Optional[str]
    citations: list[dict]
    error: Optional[str]


class AgentOrchestrator:
    """Оркестратор мультиагентной системы на LangGraph."""

    def __init__(self):
        self.router = RouterAgent()
        self.search_rag = SearchRAGAgent()
        self.summarizer = SummarizerAgent()
        self.analytics = AnalyticsAgent()

        # Строим граф
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Построить LangGraph граф."""
        workflow = StateGraph(AgentState)

        # Узлы
        workflow.add_node("router", self._route)
        workflow.add_node("search", self._search)
        workflow.add_node("summarize", self._summarize)
        workflow.add_node("analyze", self._analyze)
        workflow.add_node("finalize", self._finalize)

        # Старт
        workflow.set_entry_point("router")

        # Условные переходы от роутера
        workflow.add_conditional_edges(
            "router",
            self._decide_route,
            {
                "search": "search",
                "summarize": "summarize",
                "analyze": "analyze",
                "general": "finalize",
            },
        )

        # После каждого агента → финализация
        workflow.add_edge("search", "finalize")
        workflow.add_edge("summarize", "finalize")
        workflow.add_edge("analyze", "finalize")

        # Финализация → конец
        workflow.add_edge("finalize", END)

        try:
            workflow.compile()
            
            return workflow
        except Exception as e:
            raise ValueError(f"Error compiling workflow: {e}")

    async def _route(self, state: AgentState) -> AgentState:
        """Узел: семантический роутер."""
        try:
            decision = await self.router.route(state["query"])
            state["route"] = decision.route
            state["route_decision"] = decision
        except Exception as e:
            state["route"] = "search"
            state["error"] = str(e)
        return state

    def _decide_route(self, state: AgentState) -> Literal["search", "summarize", "analyze", "general"]:
        """Условный переход: выбор следующего узла."""
        route = state.get("route", "search")
        if route in ("search", "summarize", "analyze", "general"):
            return route
        return "search"

    async def _search(self, state: AgentState) -> AgentState:
        """Узел: Search & RAG Agent."""
        try:
            result = await self.search_rag.answer(
                query=state["query"],
                user_groups=state["user_groups"],
            )
            state["search_result"] = result
            state["citations"] = result.get("citations", [])
        except Exception as e:
            state["error"] = f"Search error: {e}"
        return state

    async def _summarize(self, state: AgentState) -> AgentState:
        """Узел: Summarizer Agent."""
        try:
            # TODO: получить текст документа по user_groups
            result = await self.summarizer.summarize(
                document_text=state["query"],
            )
            state["summary_result"] = result.model_dump()
        except Exception as e:
            state["error"] = f"Summarize error: {e}"
        return state

    async def _analyze(self, state: AgentState) -> AgentState:
        """Узел: Analytics Agent."""
        try:
            result = await self.analytics.analyze(
                document_text=state["query"],
            )
            state["analytics_result"] = result.model_dump()
        except Exception as e:
            state["error"] = f"Analytics error: {e}"
        return state

    async def _finalize(self, state: AgentState) -> AgentState:
        """Узел: финализация ответа."""
        route = state.get("route", "general")

        if route == "search" and state.get("search_result"):
            state["final_answer"] = state["search_result"]["answer"]
        elif route == "summarize" and state.get("summary_result"):
            summary = state["summary_result"]
            state["final_answer"] = (
                f"## Саммари документа\n\n{summary['summary']}\n\n"
                f"### Ключевые тезисы\n"
                + "\n".join(f"- {point}" for point in summary.get("key_points", []))
            )
        elif route == "analyze" and state.get("analytics_result"):
            analytics = state["analytics_result"]
            state["final_answer"] = (
                f"## Аналитика документа\n\n"
                f"**Тип:** {analytics.get('document_type', 'не определен')}\n"
                f"**Сложность:** {analytics.get('complexity', 'не определена')}\n\n"
                f"**Описание:** {analytics.get('summary', '')}\n\n"
                f"**Теги:** {', '.join(analytics.get('tags', []))}\n"
                f"**Связанные темы:** {', '.join(analytics.get('related_topics', []))}"
            )
        else:
            state["final_answer"] = (
                "Здравствуйте! Я — CorpAI Intelligence, ваш ассистент по корпоративным документам. "
                "Я могу помочь вам:\n"
                "- 🔍 Найти информацию в документах\n"
                "- 📄 Составить саммари документа\n"
                "- 📊 Проанализировать документ\n\n"
                "Что вас интересует?"
            )

        return state

    async def run(
        self,
        query: str,
        user_id: int,
        user_groups: list[int],
    ) -> dict:
        """Запустить оркестрацию.

        Args:
            query: Запрос пользователя.
            user_id: ID пользователя.
            user_groups: Список ID групп пользователя.

        Returns:
            dict с результатами.
        """
        initial_state: AgentState = {
            "query": query,
            "user_id": user_id,
            "user_groups": user_groups,
            "route": None,
            "route_decision": None,
            "search_result": None,
            "summary_result": None,
            "analytics_result": None,
            "final_answer": None,
            "citations": [],
            "error": None,
        }

        result = await self.graph.ainvoke(initial_state)
        return result