"""API эндпоинты для управления темами оформления артефактов (v2).

Системные темы (is_system=True) нельзя удалять или изменять.
Пользовательские темы доступны только их владельцам.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.artifact_v2 import Theme
from app.schemas.artifact_v2 import (
    ThemeResponse,
    ThemeDetailResponse,
    ThemeCreate,
    ThemeUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifact-themes", tags=["artifact-themes"])


def _get_theme(
    theme_id: int,
    db: Session,
) -> Theme:
    """Получить тему по ID без проверки владельца.

    Args:
        theme_id: ID темы.
        db: Сессия БД.

    Returns:
        Theme, если найдена.

    Raises:
        HTTPException 404: если тема не найдена.
    """
    theme = (
        db.query(Theme)
        .filter(Theme.id == theme_id)
        .first()
    )

    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        )

    return theme


def _get_user_theme(
    theme_id: int,
    user_id: int,
    db: Session,
) -> Theme:
    """Получить пользовательскую тему по ID с проверкой владельца.

    Args:
        theme_id: ID темы.
        user_id: ID пользователя (из JWT).
        db: Сессия БД.

    Returns:
        Theme, если найдена и принадлежит пользователю.

    Raises:
        HTTPException 404: если тема не найдена или принадлежит другому пользователю.
        HTTPException 403: если тема системная.
    """
    theme = _get_theme(theme_id, db)

    # Pylance: Column[bool] vs bool — false positive, SQLAlchemy Column resolves at runtime
    if theme.is_system:  # type: ignore[truthy-bool]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System themes cannot be modified or deleted",
        )

    if theme.user_id != user_id:  # type: ignore[comparison-overlap]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        )

    return theme


@router.get("/", response_model=list[ThemeResponse])
def list_themes(
    limit: int = Query(50, ge=1, le=100, description="Максимальное количество записей"),
    skip: int = Query(0, ge=0, description="Смещение для пагинации"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить список тем оформления (системные + пользовательские).

    Args:
        limit: Максимальное количество записей.
        skip: Смещение для пагинации.
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        Список ThemeResponse.
    """
    query = db.query(Theme).filter(
        (Theme.is_system.is_(True))
        | (Theme.user_id == current_user.id)
    )

    total = query.count()
    themes = (
        query
        .order_by(Theme.is_system.desc(), Theme.display_name.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [ThemeResponse.model_validate(t) for t in themes]


@router.get("/{theme_id}", response_model=ThemeDetailResponse)
def get_theme(
    theme_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить детали темы (config).

    Args:
        theme_id: ID темы.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ThemeDetailResponse с config.
    """
    theme = _get_theme(theme_id, db)
    return ThemeDetailResponse.model_validate(theme)


@router.post(
    "/",
    response_model=ThemeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_theme(
    data: ThemeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Создать пользовательскую тему оформления.

    Args:
        data: Данные для создания темы.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ThemeResponse с данными созданной темы.
    """
    # Проверяем уникальность имени
    existing = (
        db.query(Theme)
        .filter(Theme.name == data.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Theme with name '{data.name}' already exists",
        )

    theme = Theme(
        name=data.name,
        display_name=data.display_name,
        config=data.config,
        is_system=False,
        user_id=current_user.id,
    )

    db.add(theme)
    db.commit()
    db.refresh(theme)

    logger.info(f"Created theme: id={theme.id}, name={theme.name}")
    return ThemeResponse.model_validate(theme)


@router.put("/{theme_id}", response_model=ThemeResponse)
def update_theme(
    theme_id: int,
    data: ThemeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обновить пользовательскую тему (только свою, не системную).

    Args:
        theme_id: ID темы.
        data: Данные для обновления.
        current_user: Текущий пользователь.
        db: Сессия БД.

    Returns:
        ThemeResponse с обновлёнными данными.
    """
    theme = _get_user_theme(theme_id, current_user.id, db)  # type: ignore[arg-type]

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(theme, field, value)

    db.commit()
    db.refresh(theme)

    logger.info(f"Updated theme: id={theme.id}")
    return ThemeResponse.model_validate(theme)


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_theme(
    theme_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить пользовательскую тему (только свою, не системную).

    Args:
        theme_id: ID темы.
        current_user: Текущий пользователь.
        db: Сессия БД.
    """
    theme = _get_user_theme(theme_id, current_user.id, db)  # type: ignore[arg-type]

    db.delete(theme)
    db.commit()

    logger.info(f"Deleted theme: id={theme_id}")