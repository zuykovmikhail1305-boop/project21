"""LangGraph оркестратор: Router → Search/RAG → Summarizer/Analytics/ArtifactGen."""

from typing import TypedDict, Literal, Optional

try:
    from langgraph.graph import StateGraph, END
except Exception:  # pragma: no cover - optional dependency guard
    StateGraph = None
    END = None

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
        self.graph = None

        # Строим граф, если доступен LangGraph
        if StateGraph is not None:
            self._build_graph()

    def _build_graph(self) -> None:
        """Построить LangGraph граф и сохранить в self.graph."""
        if StateGraph is None:
            self.graph = None
            return

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
        import logging
        logger = logging.getLogger(__name__)
        try:
            decision = await self.router.route(state["query"])
            state["route"] = decision.route
            state["route_decision"] = decision
            logger.info("=== DIAG: Router decision: route=%s, confidence=%.2f, reasoning=%s",
                        decision.route, decision.confidence, decision.reasoning)
        except Exception as e:
            state["route"] = "search"
            state["error"] = str(e)
            logger.error("=== DIAG: Router exception: %s, falling back to 'search'", e)
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
        import logging
        logger = logging.getLogger(__name__)
        try:
            result = await self.search_rag.answer(
                query=state["query"],
                user_groups=state["user_groups"],
            )
            state["search_result"] = result
            state["citations"] = result.get("citations", [])
            answer_text = result.get("answer", "")
            chunks = result.get("chunks", [])
            logger.info("=== DIAG: Search result: answer_len=%d, n_chunks=%d, citations=%d, confidence=%s",
                        len(answer_text), len(chunks), len(result.get("citations", [])), result.get("confidence"))
            if not chunks:
                logger.warning("=== DIAG: Search returned 0 chunks! answer=%s", answer_text[:200])
        except Exception as e:
            state["error"] = f"Search error: {e}"
            logger.error("=== DIAG: Search exception: %s", e)
        return state

    async def _get_context_from_search(self, state: AgentState) -> str:
        """Получить контекст из поиска, если его ещё нет в state.

        Если search_result уже есть — использует его.
        Иначе выполняет поиск через RAG.

        Returns:
            Форматированный текст с источниками для передачи в агенты.
            Каждый чанк сопровождается указанием document_id и chunk_index.
        """
        search_result = state.get("search_result")
        if not search_result:
            try:
                search_result = await self.search_rag.answer(
                    query=state["query"],
                    user_groups=state["user_groups"],
                )
                state["search_result"] = search_result
                state["citations"] = search_result.get("citations", [])
            except Exception as e:
                state["error"] = f"Search error in context: {e}"
                return state["query"]

        # Форматируем чанки с источниками
        chunks = search_result.get("chunks", [])
        if chunks:
            context_parts = []
            for chunk in chunks[:10]:
                content = chunk.get("content", "")
                doc_id = chunk.get("document_id", "?")
                chunk_idx = chunk.get("chunk_index", "?")
                score = chunk.get("rerank_score", chunk.get("score", 0))
                if content:
                    context_parts.append(
                        f"[Источник: документ {doc_id}, чанк {chunk_idx}, "
                        f"релевантность: {score:.2f}]\n{content}"
                    )
            if context_parts:
                return "\n\n".join(context_parts)

        return search_result.get("answer", state["query"])

    async def _summarize(self, state: AgentState) -> AgentState:
        """Узел: Summarizer Agent.

        Сначала получает контекст из поиска по документам,
        затем передаёт его в Summarizer Agent.
        """
        try:
            document_text = await self._get_context_from_search(state)
            result = await self.summarizer.summarize(
                document_text=document_text,
            )
            state["summary_result"] = result.model_dump()
        except Exception as e:
            state["error"] = f"Summarize error: {e}"
        return state

    async def _analyze(self, state: AgentState) -> AgentState:
        """Узел: Analytics Agent.

        Сначала получает контекст из поиска по документам,
        затем передаёт его в Analytics Agent для анализа.
        """
        try:
            document_text = await self._get_context_from_search(state)
            result = await self.analytics.analyze(
                document_text=document_text,
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
        import logging
        logger = logging.getLogger(__name__)
        route = state.get("route", "general")
        has_search = state.get("search_result") is not None
        has_summary = state.get("summary_result") is not None
        has_analytics = state.get("analytics_result") is not None
        has_artifact = state.get("artifact_result") is not None
        error = state.get("error")

        logger.info("=== DIAG: _finalize: route=%s, has_search=%s, has_summary=%s, has_analytics=%s, has_artifact=%s, error=%s",
                    route, has_search, has_summary, has_analytics, has_artifact, error)

        if route == "search" and state.get("search_result"):
            sr = state["search_result"]
            state["final_answer"] = sr["answer"]  # type: ignore[index]
            logger.info("=== DIAG: _finalize using search_result.answer (len=%d)", len(state["final_answer"]))
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
            logger.warning("=== DIAG: _finalize FALLBACK TRIGGERED! route=%s, has_search=%s, error=%s",
                           route, has_search, error)
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

        Всегда использует роутер для определения маршрута.
        Если LangGraph недоступен — выполняет маршрут вручную.

        Args:
            query: Запрос пользователя.
            user_id: ID пользователя.
            user_groups: Список ID групп пользователя.

        Returns:
            dict с результатами.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

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

        if self.graph is None:
            # LangGraph недоступен — выполняем маршрутизацию и обработку вручную
            # 1. Роутинг
            t1 = time.time()
            initial_state = await self._route(initial_state)
            route = initial_state.get("route", "search")
            logger.info("[TIMING] orchestrator._route() took %.2fs (route=%s)", time.time() - t1, route)

            # 2. Выполнение соответствующего агента
            t2 = time.time()
            if route == "search":
                initial_state = await self._search(initial_state)
            elif route == "summarize":
                initial_state = await self._summarize(initial_state)
            elif route == "analyze":
                initial_state = await self._analyze(initial_state)
            elif route == "generate":
                initial_state = await self._generate_artifact(initial_state)
            # general — ничего не делаем, просто финализируем
            logger.info("[TIMING] orchestrator agent '%s' took %.2fs", route, time.time() - t2)

            # 3. Финализация
            initial_state = await self._finalize(initial_state)

            logger.info("[TIMING] orchestrator.run() TOTAL took %.2fs (route=%s)", time.time() - t0, route)
            return initial_state

        t1 = time.time()
        result = await self.graph.ainvoke(initial_state)
        route = result.get("route", "unknown")
        logger.info("[TIMING] orchestrator.run() LangGraph TOTAL took %.2fs (route=%s)", time.time() - t0, route)
        return result
