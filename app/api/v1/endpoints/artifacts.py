"""API эндпоинты для работы с артефактами (PDF, презентации, отчёты).

Все эндпоинты проверяют принадлежность артефакта текущему пользователю.
Попытка доступа к чужому артефакту возвращает 404 (артефакт «не найден»),
чтобы не раскрывать информацию о существовании чужих данных.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.artifact import Artifact, ArtifactStatus
from app.schemas.artifact import ArtifactResponse, ArtifactListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _get_user_artifact(
    artifact_id: int,
    user_id: int,
    db: Session,
) -> Artifact:
    """Получить артефакт по ID с проверкой принадлежности пользователю.

    Args:
        artifact_id: ID артефакта.
        user_id: ID пользователя (из JWT).
        db: Сессия БД.

    Returns:
        Artifact, если найден и принадлежит пользователю.

    Raises:
        HTTPException 404: если артефакт не найден или принадлежит другому пользователю.
    """
    artifact = (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id)
        .first()
    )

    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found",
        )

    # Проверка принадлежности пользователю
    # Pylance: Column[int] vs int — false positive, SQLAlchemy Column resolves at runtime
    if artifact.user_id != user_id:  # type: ignore[comparison-overlap]
        # Возвращаем 404 вместо 403, чтобы не раскрывать существование чужих артефактов
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found",
        )

    return artifact


@router.get("/", response_model=ArtifactListResponse)
async def list_artifacts(
    session_id: Optional[int] = Query(None, description="ID сессии чата"),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список артефактов текущего пользователя.

    Args:
        session_id: Опциональный фильтр по сессии чата.
        limit: Максимальное количество записей.
        skip: Смещение для пагинации.
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        ArtifactListResponse со списком артефактов (только свои).
    """
    query = db.query(Artifact).filter(Artifact.user_id == current_user.id)

    if session_id is not None:
        query = query.filter(Artifact.session_id == session_id)

    total = query.count()
    artifacts = (
        query
        .order_by(Artifact.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return ArtifactListResponse(
        artifacts=[ArtifactResponse.model_validate(a) for a in artifacts],
        total=total,
    )


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить информацию об артефакте.

    Args:
        artifact_id: ID артефакта.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactResponse с данными артефакта.
    """
    # Pylance: Column[int] vs int — false positive
    return _get_user_artifact(artifact_id, current_user.id, db)  # type: ignore[arg-type]


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Скачать файл артефакта.

    Проверяет:
    1. Артефакт существует
    2. Артефакт принадлежит текущему пользователю
    3. Артефакт в статусе READY
    4. Файл существует на диске

    Args:
        artifact_id: ID артефакта.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        FileResponse с файлом артефакта.
    """
    # Pylance: Column[int] vs int — false positive
    artifact = _get_user_artifact(artifact_id, current_user.id, db)  # type: ignore[arg-type]

    # Pylance: Column[Enum] vs Enum — false positive
    if artifact.status != ArtifactStatus.READY:  # type: ignore[comparison-overlap]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Artifact is not ready yet. Status: {artifact.status.value}",
        )

    # SQLAlchemy Column[str] resolves to str at runtime — cast for Pylance
    raw_path = getattr(artifact, "storage_path", None)
    storage_path: str = str(raw_path) if raw_path is not None else ""
    if not storage_path or not os.path.exists(storage_path):
        logger.error(f"Artifact file missing: id={artifact_id}, path={storage_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact file not found on storage",
        )

    # Определяем media type по типу артефакта
    media_types = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
        "md": "text/markdown",
    }

    # SQLAlchemy Column[str] resolves to str at runtime
    artifact_type: str = str(artifact.artifact_type)
    media_type = media_types.get(artifact_type, "application/octet-stream")
    filename = f"{artifact.title}.{artifact_type}"

    return FileResponse(
        path=storage_path,
        media_type=media_type,
        filename=filename,
    )


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(
    artifact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить артефакт.

    Проверяет принадлежность артефакта пользователю перед удалением.

    Args:
        artifact_id: ID артефакта.
        current_user: Текущий пользователь.
        db: Сессия БД.
    """
    # Pylance: Column[int] vs int — false positive
    artifact = _get_user_artifact(artifact_id, current_user.id, db)  # type: ignore[arg-type]

    # SQLAlchemy Column[str] resolves to str at runtime
    raw_path = getattr(artifact, "storage_path", None)
    storage_path: str = str(raw_path) if raw_path is not None else ""

    # Удаляем файл, если он существует
    if storage_path and os.path.exists(storage_path):
        try:
            os.unlink(storage_path)
            logger.info(f"Deleted artifact file: {storage_path}")
        except OSError as e:
            logger.warning(f"Failed to delete artifact file {storage_path}: {e}")

    db.delete(artifact)
    db.commit()
    logger.info(f"Deleted artifact record: id={artifact_id}")