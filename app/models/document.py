"""SQLAlchemy модели: Folder, Document, DocumentChunk, DocumentGroupPermission."""

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Enum, BigInteger, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.config import Base
import enum


class DocumentStatus(str, enum.Enum):
    """Статус обработки документа."""
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class Folder(Base):
    """Папка для иерархической организации документов."""

    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    children = relationship("Folder", backref="parent", remote_side=[id])
    documents = relationship("Document", back_populates="folder")


class Document(Base):
    """Документ (файл) в системе."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    error_message = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    folder = relationship("Folder", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    group_permissions = relationship(
        "DocumentGroupPermission",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentChunk(Base):
    """Чанк (фрагмент) документа с текстом и метаданными."""

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    chunk_type = Column(String, default="text")  # text, table, list
    chunk_metadata = Column("metadata", JSON, default=dict)  # page_number, bbox, source
    token_count = Column(Integer, default=0)
    vector_id = Column(String, nullable=True)  # UUID вектора в Qdrant
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    document = relationship("Document", back_populates="chunks")


class DocumentGroupPermission(Base):
    """ACL: права доступа групп к документам (с поддержкой deny)."""

    __tablename__ = "document_group_permissions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("user_groups.id"), nullable=False)
    permission = Column(String, default="read")  # read, write, admin
    is_deny = Column(Boolean, default=False)  # false=allow, true=deny

    # Связи
    document = relationship("Document", back_populates="group_permissions")
    group = relationship("UserGroup", back_populates="document_permissions")