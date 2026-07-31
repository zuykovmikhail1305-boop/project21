"""Pydantic схемы для API v2: проекты артефактов, версии, ассеты, шаблоны, темы."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


# === Project / Version / Asset ===


class ArtifactProjectResponse(BaseModel):
    """Схема ответа с данными проекта артефакта."""
    id: int
    user_id: int
    session_id: Optional[int] = None
    title: str
    template_name: Optional[str] = None
    current_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArtifactProjectListResponse(BaseModel):
    """Список проектов артефактов."""
    projects: list[ArtifactProjectResponse]
    total: int


class ArtifactVersionResponse(BaseModel):
    """Схема ответа с данными версии артефакта."""
    id: int
    project_id: int
    version_number: int
    status: str
    artifact_type: str
    file_size: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArtifactVersionDetailResponse(ArtifactVersionResponse):
    """Детальная схема версии с document_model и dependency_graph."""
    document_model: dict[str, Any]
    dependency_graph: dict[str, Any]
    document_validation: Optional[dict[str, Any]] = None
    render_validation: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class ArtifactAssetResponse(BaseModel):
    """Схема ответа с данными ассета."""
    id: int
    asset_id: str
    asset_type: str
    name: str
    mime_type: str
    size_bytes: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# === Template ===


class ArtifactTemplateResponse(BaseModel):
    """Схема ответа с данными шаблона."""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    is_system: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ArtifactTemplateDetailResponse(ArtifactTemplateResponse):
    """Детальная схема шаблона с schema и default_blocks."""
    schema: dict[str, Any]
    default_blocks: list[Any]


class ArtifactTemplateCreate(BaseModel):
    """Схема создания шаблона."""
    name: str
    display_name: str
    description: str
    schema: dict[str, Any]
    default_blocks: list[Any] = []


class ArtifactTemplateUpdate(BaseModel):
    """Схема обновления шаблона."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    schema: Optional[dict[str, Any]] = None
    default_blocks: Optional[list[Any]] = None


# === Theme ===


class ThemeResponse(BaseModel):
    """Схема ответа с данными темы."""
    id: int
    name: str
    display_name: str
    is_system: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ThemeDetailResponse(ThemeResponse):
    """Детальная схема темы с config."""
    config: dict[str, Any]


class ThemeCreate(BaseModel):
    """Схема создания темы."""
    name: str
    display_name: str
    config: dict[str, Any]


class ThemeUpdate(BaseModel):
    """Схема обновления темы."""
    display_name: Optional[str] = None
    config: Optional[dict[str, Any]] = None