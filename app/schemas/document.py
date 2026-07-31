"""Pydantic схемы для API: документы."""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DocumentResponse(BaseModel):
    """Схема ответа с данными документа."""
    id: int
    filename: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentDetailResponse(DocumentResponse):
    """Детальная схема документа с чанками."""
    chunks: list["DocumentChunkResponse"] = []


class DocumentChunkResponse(BaseModel):
    """Схема ответа с данными чанка."""
    id: int
    chunk_index: int
    content: str
    chunk_type: str
    token_count: int

    class Config:
        from_attributes = True


class FolderResponse(BaseModel):
    """Схема ответа с данными папки."""
    id: int
    name: str
    parent_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """Схема ответа после загрузки документа."""
    id: int
    filename: str
    status: str
    message: str = "Документ загружен и поставлен в очередь обработки"