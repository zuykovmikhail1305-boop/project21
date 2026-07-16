"""LangGraph оркестратор: Router → Search/RAG → Summarizer/Analytics/ArtifactGen."""

from typing import TypedDict, Literal, Optional
from langgraph.graph import StateGraph, END

from app.agents.router_agent import RouterAgent, RouteDecision
from app.agents.search_rag_agent import SearchRAGAgent
from app.agents.summarizer_agent import SummarizerAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.artifact_generator import ArtifactGeneratorAgent


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
    artifact_result: Optional[dict]  # результат генерации артефакта
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
        self.artifact_gen = ArtifactGeneratorAgent()

        # Строим граф
        self._build_graph()

    def _build_graph(self) -> None:
        """Построить LangGraph граф и сохранить в self.graph."""
        workflow = StateGraph(AgentState)

        # Узлы
        workflow.add_node("router", self._route)
        workflow.add_node("search", self._search)
        workflow.add_node("summarize", self._summarize)
        workflow.add_node("analyze", self._analyze)
        workflow.add_node("generate_artifact", self._generate_artifact)
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
                "generate": "generate_artifact",
                "general": "finalize",
            },
        )

        # После каждого агента → финализация
        workflow.add_edge("search", "finalize")
        workflow.add_edge("summarize", "finalize")
        workflow.add_edge("analyze", "finalize")
        workflow.add_edge("generate_artifact", "finalize")

        # Финализация → конец
        workflow.add_edge("finalize", END)

        # compile() возвращает CompiledGraph с методом ainvoke()
        self.graph = workflow.compile()  # type: ignore[assignment]

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

    def _decide_route(
        self, state: AgentState
    ) -> Literal["search", "summarize", "analyze", "generate", "general"]:
        """Условный переход: выбор следующего узла."""
        route = state.get("route", "search")
        if route in ("search", "summarize", "analyze", "generate", "general"):
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

    async def _generate_artifact(self, state: AgentState) -> AgentState:
        """Узел: Artifact Generator Agent.

        Генерирует артефакт (PDF, презентацию, отчёт) на основе
        запроса пользователя и контекста из документов.
        """
        try:
            # Получаем контекст из search_result, если он есть
            context = ""
            search_result = state.get("search_result")
            if search_result:
                context = search_result.get("answer", "")  # type: ignore[union-attr]
                # Добавляем chunks
                chunks = search_result.get("chunks", [])  # type: ignore[union-attr]
                if chunks:
                    context += "\n\n" + "\n\n".join(
                        c.get("content", "") for c in chunks[:5]
                    )

            result = await self.artifact_gen.generate(
                query=state["query"],
                context=context,
                user_id=state["user_id"],
                session_id=0,  # будет передан из API
            )
            state["artifact_result"] = result
        except Exception as e:
            state["error"] = f"Artifact generation error: {e}"
        return state

    async def _finalize(self, state: AgentState) -> AgentState:
        """Узел: финализация ответа."""
        route = state.get("route", "general")

        if route == "search" and state.get("search_result"):
            sr = state["search_result"]
            state["final_answer"] = sr["answer"]  # type: ignore[index]
        elif route == "summarize" and state.get("summary_result"):
            summary = state["summary_result"]
            state["final_answer"] = (
                f"## Саммари документа\n\n{summary['summary']}\n\n"  # type: ignore[index]
                f"### Ключевые тезисы\n"
                + "\n".join(f"- {point}" for point in summary.get("key_points", []))  # type: ignore[union-attr]
            )
        elif route == "analyze" and state.get("analytics_result"):
            analytics = state["analytics_result"]
            state["final_answer"] = (
                f"## Аналитика документа\n\n"
                f"**Тип:** {analytics.get('document_type', 'не определен')}\n"  # type: ignore[union-attr]
                f"**Сложность:** {analytics.get('complexity', 'не определена')}\n\n"  # type: ignore[union-attr]
                f"**Описание:** {analytics.get('summary', '')}\n\n"  # type: ignore[union-attr]
                f"**Теги:** {', '.join(analytics.get('tags', []))}\n"  # type: ignore[union-attr]
                f"**Связанные темы:** {', '.join(analytics.get('related_topics', []))}"  # type: ignore[union-attr]
            )
        elif route == "generate" and state.get("artifact_result"):
            artifact = state["artifact_result"]
            if artifact.get("status") == "ready":  # type: ignore[union-attr]
                state["final_answer"] = (
                    f"✅ **Артефакт сгенерирован!**\n\n"
                    f"**{artifact.get('title', 'Артефакт')}** "  # type: ignore[union-attr]
                    f"({artifact.get('artifact_type', '').upper()})\n\n"  # type: ignore[union-attr]
                    f"Файл готов к скачиванию."
                )
            elif artifact.get("status") == "error":  # type: ignore[union-attr]
                state["final_answer"] = (
                    f"❌ **Ошибка генерации артефакта:**\n"
                    f"{artifact.get('error', 'Неизвестная ошибка')}"  # type: ignore[union-attr]
                )
            else:
                state["final_answer"] = "🔄 Генерация артефакта в процессе..."
        else:
            state["final_answer"] = (
                "Здравствуйте! Я — CorpAI Intelligence, ваш ассистент по корпоративным документам. "
                "Я могу помочь вам:\n"
                "- 🔍 Найти информацию в документах\n"
                "- 📄 Составить саммари документа\n"
                "- 📊 Проанализировать документ\n"
                "- 📑 Создать отчёт или презентацию на основе документов\n\n"
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
            "artifact_result": None,
            "final_answer": None,
            "citations": [],
            "error": None,
        }

        result = await self.graph.ainvoke(initial_state)
        return result