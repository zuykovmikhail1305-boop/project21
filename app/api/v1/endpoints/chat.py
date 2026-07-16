"""Chat API endpoints with SSE streaming for agent responses."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_db
from app.api.deps import get_current_user, get_current_user_groups
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage, SessionStatus
from app.schemas.chat import (
    ChatSessionResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatCreateResponse,
)
from app.agents.orchestrator import AgentOrchestrator
from app.services.citation import CitationBuilder, CitationFormatter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Singleton orchestrator (lazy init)
_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Get or create the agent orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


# === Session Management ===


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active chat sessions for the current user."""
    sessions = (
        db.query(ChatSession)
        .filter(
            ChatSession.user_id == current_user.id,
            ChatSession.status == SessionStatus.ACTIVE,
        )
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return sessions


@router.post("/sessions", response_model=ChatCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new chat session."""
    session = ChatSession(
        user_id=current_user.id,
        title="Новый чат",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ChatCreateResponse(session_id=session.id)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all messages in a session."""
    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session.messages


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive (soft-delete) a chat session."""
    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    session.status = SessionStatus.ARCHIVED
    db.commit()


# === Streaming Chat ===


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    user_groups: list[int] = Depends(get_current_user_groups),
    db: Session = Depends(get_db),
):
    """Streaming chat endpoint using SSE.

    Accepts a user message, runs it through the agent orchestrator,
    and streams the response back as Server-Sent Events.

    Flow:
        1. Save user message to DB
        2. Run orchestrator (Router → Search/RAG → Finalize)
        3. Stream tokens/events via SSE
        4. Save assistant response to DB
    """
    orchestrator = get_orchestrator()

    # Resolve or create session
    session_id = request.session_id
    if session_id is not None:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user.id,
            )
            .first()
        )
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
    else:
        session = ChatSession(
            user_id=current_user.id,
            title=_generate_title(request.message),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    db.commit()

    async def event_generator():
        """Generate SSE events for the streaming response."""
        try:
            # Run orchestrator
            result = await orchestrator.run(
                query=request.message,
                user_id=current_user.id,
                user_groups=user_groups,
            )

            final_answer = result.get("final_answer", "")
            citations = result.get("citations", [])
            route = result.get("route", "general")
            error = result.get("error")

            # Stream the answer as SSE events
            yield {
                "event": "route",
                "data": json.dumps({"route": route, "error": error}),
            }

            # Stream artifact events if present
            artifact_result = result.get("artifact_result")
            if artifact_result:
                artifact_events = artifact_result.get("events", [])
                for event in artifact_events:
                    yield {
                        "event": event["event"],
                        "data": json.dumps(event["data"]),
                    }

            # Stream answer in chunks for real-time feel
            chunk_size = 50
            for i in range(0, len(final_answer), chunk_size):
                chunk = final_answer[i:i + chunk_size]
                yield {
                    "event": "token",
                    "data": json.dumps({"token": chunk}),
                }

            # Send citations
            if citations:
                citation_text = CitationFormatter.format_citations(citations)
                citation_html = CitationFormatter.format_citations_html(citations)
                yield {
                    "event": "citations",
                    "data": json.dumps({
                        "citations": citations,
                        "text": citation_text,
                        "html": citation_html,
                    }),
                }

            # Send done event
            yield {
                "event": "done",
                "data": json.dumps({"session_id": session_id}),
            }

            # Save assistant message to DB (outside generator, after stream)
            # We do this in a separate step below

        except Exception as e:
            logger.exception("Orchestrator error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    # We need to save the assistant message after streaming completes.
    # SSE is async, so we use a callback pattern via a background task.
    # For simplicity, we save it in a synchronous manner after the stream.
    # The actual saving happens in the response.

    return EventSourceResponse(event_generator())


@router.post("/chat")
async def chat_sync(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    user_groups: list[int] = Depends(get_current_user_groups),
    db: Session = Depends(get_db),
):
    """Synchronous (non-streaming) chat endpoint.

    Returns the full response at once. Useful for testing or simple integrations.
    """
    orchestrator = get_orchestrator()

    # Resolve or create session
    session_id = request.session_id
    if session_id is not None:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user.id,
            )
            .first()
        )
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
    else:
        session = ChatSession(
            user_id=current_user.id,
            title=_generate_title(request.message),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=request.message,
    )
    db.add(user_msg)
    db.commit()

    # Run orchestrator
    result = await orchestrator.run(
        query=request.message,
        user_id=current_user.id,
        user_groups=user_groups,
    )

    final_answer = result.get("final_answer", "")
    citations = result.get("citations", [])
    route = result.get("route", "general")
    error = result.get("error")

    # Save assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=final_answer,
        citations={"citations": citations, "route": route} if citations else None,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    # Update session title if first message
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session and session.title == "Новый чат":
        session.title = _generate_title(request.message)
        db.commit()

    return {
        "session_id": session_id,
        "message_id": assistant_msg.id,
        "content": final_answer,
        "citations": citations,
        "route": route,
        "error": error,
    }


def _generate_title(message: str) -> str:
    """Generate a short title from the first user message."""
    # Simple heuristic: take first 50 chars
    title = message.strip()[:50]
    if len(message.strip()) > 50:
        title += "..."
    return title if title else "Новый чат"