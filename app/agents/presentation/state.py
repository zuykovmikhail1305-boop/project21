"""PresentationState — единое состояние для multi-agent presentation pipeline.

Все агенты читают и пишут в это состояние.
Executive router (Python node) принимает решения на основе флагов.
"""

from typing import Optional, TypedDict

from app.agents.presentation.models import (
    IntentResult,
    PresentationOutline,
    ResearchResult,
    ReviewResult,
    Slide,
)


class PresentationState(TypedDict):
    """Единое состояние для всего presentation pipeline.

    Каждый агент заполняет свою часть состояния.
    Executive router смотрит на current_node и флаги в результатах.
    """

    # === Original request ===
    query: str
    user_id: int
    user_groups: list[int]

    # === Agent outputs (populated sequentially) ===
    intent: Optional[IntentResult]
    research: Optional[ResearchResult]
    outline: Optional[PresentationOutline]
    slides: Optional[list[Slide]]
    review: Optional[ReviewResult]

    # === Control flow ===
    current_node: str  # Which node just finished (for executive router)
    iteration: int  # Current review iteration
    max_iterations: int  # Max review loops before force-finish
    error: Optional[str]

    # === Final artifact ===
    artifact_result: Optional[dict]