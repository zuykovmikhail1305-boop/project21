# Multi-Agent Architecture for Presentation Generation v2

## 1. LangGraph Flow

```text
                User
                  │
                  ▼
              Intent
              Agent
                  │
                  ▼
             Research
              Agent
             ↙        ↘
   мало данных      достаточно
        │               │
        ▼               ▼
   Reformulate      Planner
      Query          Agent
        ▲               │
        └───────────────▼
                     Writer
                     Agent
                        │
                        ▼
                   Reviewer
                   Agent
                   ↙       ↘
              approve     revise
                             │
                             └────► Writer
```

## 2. Executive Node (Python, не LLM)

Центральный узел оркестрации — простая Python-логика, без вызова LLM.

```python
def executive_router(state: PresentationState) -> str:
    """Принимает решение: куда направить поток."""
    
    # После Research: достаточно ли данных?
    if state.current_node == "research":
        if state.research and state.research.has_sufficient_data:
            return "planner"
        else:
            return "reformulate_query"
    
    # После Reviewer: нужны ли правки?
    if state.current_node == "reviewer":
        if state.review and state.review.needs_revision:
            if state.iteration < state.max_iterations:
                return "writer"  # отправить на доработку
            else:
                return "finish"  # превышен лимит итераций
        else:
            return "finish"
    
    # По умолчанию — следующий шаг
    return "finish"
```

## 3. PresentationState

```python
class PresentationState(TypedDict):
    # Original request
    query: str
    user_id: int
    user_groups: list[int]
    
    # Agent outputs
    intent: Optional[IntentResult]
    research: Optional[ResearchResult]
    outline: Optional[PresentationOutline]
    slides: Optional[list[Slide]]
    review: Optional[ReviewResult]
    
    # Control
    current_node: str  # current node name for executive router
    iteration: int
    max_iterations: int
    error: Optional[str]
    
    # Final artifact
    artifact_result: Optional[dict]
```

## 4. Agent Models

### 4.1 Intent Agent

```python
class IntentResult(BaseModel):
    title: str
    goal: str  # "inform" | "persuade" | "educate" | "report"
    audience: str  # "investors" | "management" | "team" | "general"
    tone: str  # "formal" | "neutral" | "casual"
    key_topics: list[str]
    constraints: list[str]
    suggested_slide_count: int
```

### 4.2 Research Agent

```python
class ResearchResult(BaseModel):
    summary: str
    key_facts: list[str]
    statistics: list[dict]
    citations: list[dict]
    has_sufficient_data: bool
    data_gaps: list[str]
    suggested_queries: list[str]  # для Reformulate Query
```

### 4.3 Planner Agent

Planner НЕ пишет текст. Только структуру.

```python
class SlideOutline(BaseModel):
    title: str
    slide_type: str  # "title" | "content" | "section_divider" | "data" | "comparison" | "summary"
    goal: str  # что этот слайд должен коммуницировать
    required_data: list[str]  # ссылки на ResearchResult.key_facts / statistics
    suggested_layout: str  # "title_only" | "bullets" | "chart" | "two_column" | "quote"

class PresentationOutline(BaseModel):
    title: str
    total_slides: int
    narrative_flow: str  # "problem-solution" | "chronological" | "comparative" | "topical"
    slides: list[SlideOutline]
```

### 4.4 Writer Agent

Пишет контент для ОДНОГО слайда. Вызывается N раз (по числу слайдов).

```python
class SlideBlock(BaseModel):
    type: str  # "heading" | "paragraph" | "bullet_list" | "chart" | "table" | "quote"
    data: dict  # {"text": ..., "items": [...], "level": ...}

class Slide(BaseModel):
    slide_index: int
    title: str
    blocks: list[SlideBlock]
    key_message: str  # что этот слайд коммуницирует
    citations: list[str]
```

### 4.5 Reviewer Agent

Проверяет структурное представление ДО рендера.

```python
class ReviewIssue(BaseModel):
    severity: str  # "critical" | "warning" | "suggestion"
    slide_index: Optional[int]
    category: str  # "content" | "structure" | "data" | "consistency"
    description: str
    fix_suggestion: str

class ReviewResult(BaseModel):
    needs_revision: bool
    issues: list[ReviewIssue]
    overall_score: float  # 0.0 - 1.0
    summary: str  # общая оценка презентации
```

## 5. LangGraph Implementation

```python
def _build_presentation_graph(self) -> None:
    workflow = StateGraph(PresentationState)
    
    # Nodes
    workflow.add_node("intent", self._run_intent)
    workflow.add_node("research", self._run_research)
    workflow.add_node("reformulate_query", self._run_reformulate)
    workflow.add_node("planner", self._run_planner)
    workflow.add_node("writer", self._run_writer)
    workflow.add_node("reviewer", self._run_reviewer)
    workflow.add_node("executive", self._run_executive)
    workflow.add_node("finish", self._finalize_presentation)
    
    # Entry point
    workflow.set_entry_point("intent")
    
    # Linear flow with executive routing
    workflow.add_edge("intent", "research")
    workflow.add_edge("research", "executive")
    workflow.add_edge("reformulate_query", "research")  # loop back
    workflow.add_edge("planner", "writer")
    workflow.add_edge("writer", "reviewer")
    workflow.add_edge("reviewer", "executive")
    
    # Executive decides where to go
    workflow.add_conditional_edges(
        "executive",
        self._executive_router,
        {
            "planner": "planner",
            "reformulate_query": "reformulate_query",
            "writer": "writer",
            "finish": "finish",
        },
    )
    
    workflow.add_edge("finish", END)
    self.presentation_graph = workflow.compile()
```

## 6. Executive Router Logic

```python
def _executive_router(self, state: PresentationState) -> str:
    """Pure Python routing logic — no LLM calls."""
    
    # After research
    if state.get("current_node") == "research":
        research = state.get("research")
        if research and research.get("has_sufficient_data"):
            return "planner"
        else:
            return "reformulate_query"
    
    # After reviewer
    if state.get("current_node") == "reviewer":
        review = state.get("review")
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", 3)
        
        if review and review.get("needs_revision"):
            if iteration < max_iter:
                state["iteration"] = iteration + 1
                return "writer"
            else:
                return "finish"  # max iterations reached
        else:
            return "finish"
    
    return "finish"
```

## 7. Integration with Existing Orchestrator

Текущий [`app/agents/orchestrator.py`](app/agents/orchestrator.py) имеет маршрут `generate`, который ведёт в `_generate_artifact()`. 

**Изменение:** `_generate_artifact()` будет запускать presentation-граф вместо прямого вызова `ArtifactGeneratorAgent`.

```python
async def _generate_artifact(self, state: AgentState) -> AgentState:
    """Узел: запускает multi-agent presentation pipeline."""
    
    # Инициализируем presentation state
    pres_state: PresentationState = {
        "query": state["query"],
        "user_id": state["user_id"],
        "user_groups": state["user_groups"],
        "intent": None,
        "research": None,
        "outline": None,
        "slides": None,
        "review": None,
        "current_node": "intent",
        "iteration": 0,
        "max_iterations": 3,
        "error": None,
        "artifact_result": None,
    }
    
    # Запускаем presentation-граф
    result = await self.presentation_graph.ainvoke(pres_state)
    
    # Конвертируем результат в artifact_result
    state["artifact_result"] = self._presentation_to_artifact(result)
    return state
```

## 8. Что остаётся от текущей v2 архитектуры

### Сохраняется:
- [`app/services/artifact/models.py`](app/services/artifact/models.py) — `DocumentModel`, `Block`, `Section`, `Theme`, `ArtifactContext`
- [`app/services/artifact/document_builder.py`](app/services/artifact/document_builder.py) — `DocumentBuilder.build()` (конвертация Slide → DocumentModel)
- [`app/services/artifact/marp_renderer.py`](app/services/artifact/marp_renderer.py) — Marp CLI rendering
- [`app/services/artifact/renderer_factory.py`](app/services/artifact/renderer_factory.py) — Render orchestration
- [`app/services/artifact/validator.py`](app/services/artifact/validator.py) — Document validation
- [`app/services/artifact/marp_generator.py`](app/services/artifact/marp_generator.py) — Markdown generation

### Заменяется:
- [`app/agents/artifact_generator.py`](app/agents/artifact_generator.py) — заменяется на multi-agent pipeline
- [`app/agents/orchestrator.py`](app/agents/orchestrator.py) — добавляется presentation-граф

### Добавляется:
- `app/agents/presentation/__init__.py`
- `app/agents/presentation/models.py` — все новые Pydantic модели
- `app/agents/presentation/state.py` — PresentationState
- `app/agents/presentation/intent_agent.py` — Intent Agent
- `app/agents/presentation/research_agent.py` — Research Agent
- `app/agents/presentation/planner_agent.py` — Planner Agent
- `app/agents/presentation/writer_agent.py` — Writer Agent
- `app/agents/presentation/reviewer_agent.py` — Reviewer Agent

## 9. MVP Implementation Order

### Phase 1: Foundation
1. Create `app/agents/presentation/` package
2. Implement `models.py` (all Pydantic models)
3. Implement `state.py` (PresentationState)
4. Implement Intent Agent (simplest — validates the approach)

### Phase 2: Core Pipeline
5. Implement Research Agent (wraps existing SearchRAGAgent)
6. Implement Planner Agent (outline only, no content)
7. Implement Writer Agent (per-slide content)
8. Implement Reviewer Agent (structural checks)

### Phase 3: Integration
9. Add presentation graph to orchestrator
10. Connect executive router
11. Integration tests
12. Remove old artifact_generator.py

## 10. Key Design Principles

1. **Planner не пишет текст** — только структура, типы слайдов, цели
2. **Writer пишет 1 слайд за раз** — каждый вызов простой, параллелизуется
3. **Reviewer проверяет до рендера** — 80% проблем отлавливаются на структурном уровне
4. **Executive Node — это Python, не LLM** — простая логика по флагам
5. **Общий State** — все агенты читают/пишут в единое состояние
6. **Condition Nodes** — не линейный pipeline, а граф с развилками