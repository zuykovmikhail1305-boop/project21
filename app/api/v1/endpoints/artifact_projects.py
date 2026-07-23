"""API эндпоинты для управления проектами артефактов и версиями (v2).

Все эндпоинты проверяют принадлежность проекта текущему пользователю.
Попытка доступа к чужому проекту возвращает 404 (проект «не найден»),
чтобы не раскрывать информацию о существовании чужих данных.
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.artifact_v2 import ArtifactProject, ArtifactVersion, ArtifactAsset
from app.schemas.artifact_v2 import (
    ArtifactProjectResponse,
    ArtifactProjectListResponse,
    ArtifactVersionResponse,
    ArtifactVersionDetailResponse,
    ArtifactAssetResponse,
)
from app.services.artifact.models import ArtifactStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifact-projects", tags=["artifact-projects"])


def _get_user_project(
    project_id: int,
    user_id: int,
    db: Session,
) -> ArtifactProject:
    """Получить проект по ID с проверкой принадлежности пользователю.

    Args:
        project_id: ID проекта.
        user_id: ID пользователя (из JWT).
        db: Сессия БД.

    Returns:
        ArtifactProject, если найден и принадлежит пользователю.

    Raises:
        HTTPException 404: если проект не найден или принадлежит другому пользователю.
    """
    project = (
        db.query(ArtifactProject)
        .filter(ArtifactProject.id == project_id)
        .first()
    )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Проверка принадлежности пользователю
    if project.user_id != user_id:  # type: ignore[comparison-overlap]
        # Возвращаем 404 вместо 403, чтобы не раскрывать существование чужих проектов
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return project


def _get_user_version(
    version_id: int,
    project_id: int,
    user_id: int,
    db: Session,
) -> ArtifactVersion:
    """Получить версию по ID с проверкой принадлежности проекта пользователю.

    Args:
        version_id: ID версии.
        project_id: ID проекта.
        user_id: ID пользователя (из JWT).
        db: Сессия БД.

    Returns:
        ArtifactVersion, если найдена и принадлежит пользователю.

    Raises:
        HTTPException 404: если версия не найдена или проект принадлежит другому пользователю.
    """
    # Сначала проверяем доступ к проекту
    _get_user_project(project_id, user_id, db)

    version = (
        db.query(ArtifactVersion)
        .filter(
            ArtifactVersion.id == version_id,
            ArtifactVersion.project_id == project_id,
        )
        .first()
    )

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    return version


@router.get("/", response_model=ArtifactProjectListResponse)
def list_projects(
    limit: int = Query(50, ge=1, le=100, description="Максимальное количество записей"),
    skip: int = Query(0, ge=0, description="Смещение для пагинации"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список проектов артефактов текущего пользователя.

    Args:
        limit: Максимальное количество записей.
        skip: Смещение для пагинации.
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        ArtifactProjectListResponse со списком проектов (только свои).
    """
    query = db.query(ArtifactProject).filter(
        ArtifactProject.user_id == current_user.id
    )

    total = query.count()
    projects = (
        query
        .order_by(ArtifactProject.updated_at.desc().nullslast(), ArtifactProject.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return ArtifactProjectListResponse(
        projects=[ArtifactProjectResponse.model_validate(p) for p in projects],
        total=total,
    )


@router.get("/{project_id}", response_model=ArtifactProjectResponse)
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить детали проекта артефакта.

    Args:
        project_id: ID проекта.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactProjectResponse с данными проекта.
    """
    return _get_user_project(project_id, current_user.id, db)  # type: ignore[arg-type]


@router.get("/{project_id}/versions", response_model=list[ArtifactVersionResponse])
def list_versions(
    project_id: int,
    limit: int = Query(50, ge=1, le=100, description="Максимальное количество записей"),
    skip: int = Query(0, ge=0, description="Смещение для пагинации"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список версий проекта.

    Args:
        project_id: ID проекта.
        limit: Максимальное количество записей.
        skip: Смещение для пагинации.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        Список ArtifactVersionResponse.
    """
    # Проверяем доступ к проекту
    _get_user_project(project_id, current_user.id, db)  # type: ignore[arg-type]

    versions = (
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.project_id == project_id)
        .order_by(ArtifactVersion.version_number.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [ArtifactVersionResponse.model_validate(v) for v in versions]


@router.get(
    "/{project_id}/versions/{version_id}",
    response_model=ArtifactVersionDetailResponse,
)
def get_version(
    project_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить детали версии артефакта (document_model, dependency_graph).

    Args:
        project_id: ID проекта.
        version_id: ID версии.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactVersionDetailResponse с document_model и dependency_graph.
    """
    version = _get_user_version(version_id, project_id, current_user.id, db)  # type: ignore[arg-type]
    return ArtifactVersionDetailResponse.model_validate(version)


@router.get(
    "/{project_id}/versions/{version_id}/assets",
    response_model=list[ArtifactAssetResponse],
)
def list_version_assets(
    project_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список ассетов версии.

    Args:
        project_id: ID проекта.
        version_id: ID версии.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        Список ArtifactAssetResponse.
    """
    # Проверяем доступ к версии (и проекту)
    _get_user_version(version_id, project_id, current_user.id, db)  # type: ignore[arg-type]

    assets = (
        db.query(ArtifactAsset)
        .filter(ArtifactAsset.version_id == version_id)
        .order_by(ArtifactAsset.created_at.desc())
        .all()
    )

    return [ArtifactAssetResponse.model_validate(a) for a in assets]


@router.get("/{project_id}/versions/{version_id}/download")
def download_version(
    project_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Скачать файл версии артефакта.

    Проверяет:
    1. Версия существует и принадлежит пользователю
    2. Версия в статусе READY
    3. Файл существует на диске

    Args:
        project_id: ID проекта.
        version_id: ID версии.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        FileResponse с файлом версии.
    """
    version = _get_user_version(version_id, project_id, current_user.id, db)  # type: ignore[arg-type]

    # Проверяем статус
    if version.status != ArtifactStatus.READY:  # type: ignore[comparison-overlap]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Version is not ready yet. Status: {version.status.value}",
        )

    # Проверяем файл на диске
    raw_path = getattr(version, "storage_path", None)
    storage_path: str = str(raw_path) if raw_path is not None else ""
    if not storage_path or not os.path.exists(storage_path):
        logger.error(f"Version file missing: id={version_id}, path={storage_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version file not found on storage",
        )

    # Определяем media type по типу артефакта
    media_types = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
        "md": "text/markdown",
    }

    artifact_type: str = str(version.artifact_type)
    media_type = media_types.get(artifact_type, "application/octet-stream")
    filename = f"v{version.version_number}-{storage_path.split(os.sep)[-1] or 'artifact'}.{artifact_type}"

    return FileResponse(
        path=storage_path,
        media_type=media_type,
        filename=filename,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить проект артефакта со всеми версиями, ассетами и файлами.

    Проверяет принадлежность проекта пользователю перед удалением.
    Каскадное удаление версий и ассетов настроено на уровне БД (CASCADE).

    Args:
        project_id: ID проекта.
        current_user: Текущий пользователь.
        db: Сессия БД.
    """
    project = _get_user_project(project_id, current_user.id, db)  # type: ignore[arg-type]

    # Удаляем файлы всех версий проекта
    versions = (
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.project_id == project_id)
        .all()
    )
    for version in versions:
        raw_path = getattr(version, "storage_path", None)
        storage_path: str = str(raw_path) if raw_path is not None else ""
        if storage_path and os.path.exists(storage_path):
            try:
                os.unlink(storage_path)
                logger.info(f"Deleted version file: {storage_path}")
            except OSError as e:
                logger.warning(f"Failed to delete version file {storage_path}: {e}")

    # Удаляем файлы ассетов
    version_ids = [v.id for v in versions]
    if version_ids:
        assets = (
            db.query(ArtifactAsset)
            .filter(ArtifactAsset.version_id.in_(version_ids))
            .all()
        )
        for asset in assets:
            raw_path = getattr(asset, "storage_path", None)
            storage_path: str = str(raw_path) if raw_path is not None else ""
            if storage_path and os.path.exists(storage_path):
                try:
                    os.unlink(storage_path)
                    logger.info(f"Deleted asset file: {storage_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete asset file {storage_path}: {e}")

    # Удаляем проект (CASCADE удалит версии и ассеты в БД)
    db.delete(project)
    db.commit()
    logger.info(f"Deleted project: id={project_id}")