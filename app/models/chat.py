"""SQLAlchemy модели: ChatSession, ChatMessage."""

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.config import Base
import enum


class SessionStatus(str, enum.Enum):
    """Статус сессии чата."""
    ACTIVE = "active"
    ARCHIVED = "archived"


class ChatSession(Base):
    """Сессия чата пользователя с агентом."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, default="Новый чат")
    status = Column(Enum(SessionStatus), default=SessionStatus.ACTIVE)
    agent_state = Column(JSON, nullable=True)  # LangGraph state
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    """Сообщение в чате."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)  # chunk_id, source_links
    validation_result = Column(JSON, nullable=True)  # NLI check result
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    session = relationship("ChatSession", back_populates="messages")