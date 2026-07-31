"""Мультиагентная система на LangGraph."""

try:
    from app.agents.orchestrator import AgentOrchestrator
except Exception:  # pragma: no cover - optional dependency guard
    AgentOrchestrator = None

__all__ = ["AgentOrchestrator"]
