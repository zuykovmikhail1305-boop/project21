"""SQLAlchemy модель: Artifact (сгенерированные артефакты: PDF, презентации, отчёты)."""

from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.config import Base
import enum


class ArtifactStatus(str, enum.Enum):
    """Статус генерации артефакта."""
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class Artifact(Base):
    """Сгенерированный артефакт (PDF, презентация, отчёт, дашборд)."""

    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    artifact_type = Column(String, nullable=False)  # pdf, pptx, docx, md, html
    title = Column(String, nullable=False)
    status = Column(Enum(ArtifactStatus), default=ArtifactStatus.GENERATING)
    storage_path = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    source_message_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    session = relationship("ChatSession", backref="artifacts")
    user = relationship("User", backref="artifacts")