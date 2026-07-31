"""Multi-agent presentation generation pipeline.

Agents:
    IntentAgent — extracts presentation goal, audience, tone from user query
    ResearchAgent — gathers context from documents via SearchRAGAgent
    PlannerAgent — designs presentation outline (slides, types, goals)
    WriterAgent — generates content for individual slides
    ReviewerAgent — quality checks structural representation before rendering

Executive router (Python node, not LLM) orchestrates the flow with conditional edges.
"""

from app.agents.presentation.intent_agent import IntentAgent
from app.agents.presentation.research_agent import ResearchAgent
from app.agents.presentation.planner_agent import PlannerAgent
from app.agents.presentation.writer_agent import WriterAgent
from app.agents.presentation.reviewer_agent import ReviewerAgent

__all__ = [
    "IntentAgent",
    "ResearchAgent",
    "PlannerAgent",
    "WriterAgent",
    "ReviewerAgent",
]