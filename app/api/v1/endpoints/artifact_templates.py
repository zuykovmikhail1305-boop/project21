"""API эндпоинты для управления шаблонами артефактов (v2).

Системные шаблоны (is_system=True) нельзя удалять или изменять.
Пользовательские шаблоны доступны только их владельцам.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.artifact_v2 import ArtifactTemplate
from app.schemas.artifact_v2 import (
    ArtifactTemplateResponse,
    ArtifactTemplateDetailResponse,
    ArtifactTemplateCreate,
    ArtifactTemplateUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifact-templates", tags=["artifact-templates"])


def _get_template(
    template_id: int,
    db: Session,
) -> ArtifactTemplate:
    """Получить шаблон по ID без проверки владельца.

    Args:
        template_id: ID шаблона.
        db: Сессия БД.

    Returns:
        ArtifactTemplate, если найден.

    Raises:
        HTTPException 404: если шаблон не найден.
    """
    template = (
        db.query(ArtifactTemplate)
        .filter(ArtifactTemplate.id == template_id)
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return template


def _get_user_template(
    template_id: int,
    user_id: int,
    db: Session,
) -> ArtifactTemplate:
    """Получить пользовательский шаблон по ID с проверкой владельца.

    Args:
        template_id: ID шаблона.
        user_id: ID пользователя (из JWT).
        db: Сессия БД.

    Returns:
        ArtifactTemplate, если найден и принадлежит пользователю.

    Raises:
        HTTPException 404: если шаблон не найден или принадлежит другому пользователю.
        HTTPException 403: если шаблон системный.
    """
    template = _get_template(template_id, db)

    # Pylance: Column[bool] vs bool — false positive, SQLAlchemy Column resolves at runtime
    if template.is_system:  # type: ignore[truthy-bool]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System templates cannot be modified or deleted",
        )

    if template.user_id != user_id:  # type: ignore[comparison-overlap]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return template


@router.get("/", response_model=list[ArtifactTemplateResponse])
def list_templates(
    limit: int = Query(50, ge=1, le=100, description="Максимальное количество записей"),
    skip: int = Query(0, ge=0, description="Смещение для пагинации"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список шаблонов артефактов (системные + пользовательские).

    Args:
        limit: Максимальное количество записей.
        skip: Смещение для пагинации.
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        Список ArtifactTemplateResponse.
    """
    query = db.query(ArtifactTemplate).filter(
        (ArtifactTemplate.is_system.is_(True))
        | (ArtifactTemplate.user_id == current_user.id)
    )

    total = query.count()
    templates = (
        query
        .order_by(ArtifactTemplate.is_system.desc(), ArtifactTemplate.display_name.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [ArtifactTemplateResponse.model_validate(t) for t in templates]


@router.get("/{template_id}", response_model=ArtifactTemplateDetailResponse)
def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить детали шаблона (schema, default_blocks).

    Args:
        template_id: ID шаблона.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactTemplateDetailResponse с schema и default_blocks.
    """
    template = _get_template(template_id, db)
    return ArtifactTemplateDetailResponse.model_validate(template)


@router.post(
    "/",
    response_model=ArtifactTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    data: ArtifactTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Создать пользовательский шаблон артефакта.

    Args:
        data: Данные для создания шаблона.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactTemplateResponse с данными созданного шаблона.
    """
    # Проверяем уникальность имени
    existing = (
        db.query(ArtifactTemplate)
        .filter(ArtifactTemplate.name == data.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template with name '{data.name}' already exists",
        )

    template = ArtifactTemplate(
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        schema=data.schema,
        default_blocks=data.default_blocks,
        is_system=False,
        user_id=current_user.id,
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    logger.info(f"Created template: id={template.id}, name={template.name}")
    return ArtifactTemplateResponse.model_validate(template)


@router.put("/{template_id}", response_model=ArtifactTemplateResponse)
def update_template(
    template_id: int,
    data: ArtifactTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обновить пользовательский шаблон (только свой, не системный).

    Args:
        template_id: ID шаблона.
        data: Данные для обновления.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ArtifactTemplateResponse с обновлёнными данными.
    """
    template = _get_user_template(template_id, current_user.id, db)  # type: ignore[arg-type]

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    db.commit()
    db.refresh(template)

    logger.info(f"Updated template: id={template.id}")
    return ArtifactTemplateResponse.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить пользовательский шаблон (только свой, не системный).

    Args:
        template_id: ID шаблона.
        current_user: Текущий пользователь.
        db: Сессия БД.
    """
    template = _get_user_template(template_id, current_user.id, db)  # type: ignore[arg-type]

    db.delete(template)
    db.commit()

    logger.info(f"Deleted template: id={template_id}")