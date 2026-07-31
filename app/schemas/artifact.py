"""Pydantic схемы для API: артефакты (PDF, презентации, отчёты)."""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ArtifactResponse(BaseModel):
    """Схема ответа с данными артефакта."""
    id: int
    session_id: int
    artifact_type: str
    title: str
    status: str
    file_size: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArtifactDownloadResponse(BaseModel):
    """Схема ответа с URL для скачивания артефакта."""
    id: int
    filename: str
    download_url: str
    file_size: Optional[int] = None


class ArtifactListResponse(BaseModel):
    """Список артефактов."""
    artifacts: list[ArtifactResponse]
    total: int