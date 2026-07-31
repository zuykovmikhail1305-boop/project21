"""SQLAlchemy модели для новой архитектуры генерации артефактов v2.

ArtifactProject — контейнер для версий.
ArtifactVersion — полный слепок артефакта.
ArtifactAsset — ассет (изображение, график, диаграмма, ...).
ArtifactTemplate — шаблон артефакта.
Theme — тема оформления.
"""

from sqlalchemy import (
    Column, Integer, String, BigInteger, Boolean,
    ForeignKey, DateTime, Enum, Text, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.config import Base
from app.services.artifact.models import ArtifactStatus, AssetType


class ArtifactProject(Base):
    """Проект артефакта — контейнер для версий."""

    __tablename__ = "artifact_projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    title = Column(String, nullable=False)
    template_name = Column(String, nullable=True)
    current_version = Column(Integer, default=1)
    context = Column(JSON, nullable=True)  # ArtifactContext
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    user = relationship("User", backref="artifact_projects")
    session = relationship("ChatSession", backref="artifact_projects")
    versions = relationship(
        "ArtifactVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ArtifactVersion.version_number.desc()",
    )


class ArtifactVersion(Base):
    """Версия артефакта — полный слепок."""

    __tablename__ = "artifact_versions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("artifact_projects.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(Enum(ArtifactStatus), default=ArtifactStatus.GENERATING)
    document_model = Column(JSON, nullable=True)  # DocumentModel — единый источник истины
    dependency_graph = Column(JSON, nullable=True)
    storage_path = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    artifact_type = Column(String, nullable=False)  # pdf, pptx, docx, md, html
    document_validation = Column(JSON, nullable=True)  # результаты DocumentValidator
    render_validation = Column(JSON, nullable=True)  # результаты RenderValidator
    parent_version_id = Column(Integer, ForeignKey("artifact_versions.id"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    project = relationship("ArtifactProject", back_populates="versions", foreign_keys=[project_id])
    parent_version = relationship("ArtifactVersion", back_populates="child_versions", remote_side=[id])
    child_versions = relationship("ArtifactVersion", back_populates="parent_version", remote_side=[parent_version_id])
    assets = relationship(
        "ArtifactAsset",
        back_populates="version",
        cascade="all, delete-orphan",
    )


class ArtifactAsset(Base):
    """Ассет — изображение, график, диаграмма, таблица, логотип, формула."""

    __tablename__ = "artifact_assets"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(String, unique=True, nullable=False, index=True)  # UUID для ссылок из DocumentModel
    version_id = Column(Integer, ForeignKey("artifact_versions.id"), nullable=False)
    asset_type = Column(Enum(AssetType), nullable=False)
    name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    asset_metadata = Column("metadata", JSON, default={})
    size_bytes = Column(BigInteger, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    version = relationship("ArtifactVersion", back_populates="assets", foreign_keys=[version_id])


class ArtifactTemplate(Base):
    """Шаблон артефакта — предопределённая структура."""

    __tablename__ = "artifact_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    schema = Column(JSON, nullable=False)  # JSON Schema для ArtifactPlan
    default_blocks = Column(JSON, nullable=True)  # блоки по умолчанию
    is_system = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    user = relationship("User", backref="artifact_templates")


class Theme(Base):
    """Тема оформления."""

    __tablename__ = "themes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    is_system = Column(Boolean, default=False)
    config = Column(JSON, nullable=False)  # полная конфигурация Theme (Pydantic model)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    user = relationship("User", backref="themes")