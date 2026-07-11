"""API эндпоинты для пользователей (в т.ч. admin)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.api.deps import get_current_user, get_current_admin_user
from app.crud.crud_user import get_user_by_id, get_users, update_user, delete_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Информация о текущем пользователе",
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Получить информацию о текущем аутентифицированном пользователе.

    Args:
        current_user: Текущий пользователь (из JWT access token).

    Returns:
        UserResponse с id, email, username, is_active, created_at.
    """
    return UserResponse(
        id=current_user.id,  # type: ignore[arg-type]
        email=str(current_user.email),
        username=str(current_user.username),
        is_active=bool(current_user.is_active),
        created_at=current_user.created_at,  # type: ignore[arg-type]
    )


# ===================== Admin endpoints =====================


@router.get(
    "/",
    response_model=list[UserResponse],
    summary="Список пользователей (admin)",
)
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Получить список пользователей с пагинацией.

    Только для администраторов (группа admins).

    Args:
        skip: Смещение.
        limit: Лимит записей.
        db: Сессия БД.
        admin_user: Текущий администратор (из JWT + проверка группы admins).

    Returns:
        Список UserResponse.
    """
    users = get_users(db, skip=skip, limit=limit)
    return [
        UserResponse(
            id=u.id,  # type: ignore[arg-type]
            email=str(u.email),
            username=str(u.username),
            is_active=bool(u.is_active),
            created_at=u.created_at,  # type: ignore[arg-type]
        )
        for u in users
    ]


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Получить пользователя по ID (admin)",
)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Получить пользователя по ID.

    Только для администраторов (группа admins).

    Args:
        user_id: ID пользователя.
        db: Сессия БД.
        admin_user: Текущий администратор.

    Returns:
        UserResponse.

    Raises:
        HTTPException 404: Если пользователь не найден.
    """
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        id=user.id,  # type: ignore[arg-type]
        email=str(user.email),
        username=str(user.username),
        is_active=bool(user.is_active),
        created_at=user.created_at,  # type: ignore[arg-type]
    )


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Обновить пользователя (admin)",
)
async def update_user_info(
    user_id: int,
    user_update: dict,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Обновить данные пользователя.

    Только для администраторов (группа admins).
    Можно обновлять: username, is_active.

    Args:
        user_id: ID пользователя.
        user_update: Поля для обновления.
        db: Сессия БД.
        admin_user: Текущий администратор.

    Returns:
        Обновлённый UserResponse.

    Raises:
        HTTPException 404: Если пользователь не найден.
    """
    # Фильтруем только разрешённые поля
    allowed_fields = {"username", "is_active"}
    filtered_update = {k: v for k, v in user_update.items() if k in allowed_fields}

    user = update_user(db, user_id=user_id, **filtered_update)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        id=user.id,  # type: ignore[arg-type]
        email=str(user.email),
        username=str(user.username),
        is_active=bool(user.is_active),
        created_at=user.created_at,  # type: ignore[arg-type]
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить пользователя (admin)",
)
async def delete_user_info(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Удалить пользователя.

    Только для администраторов (группа admins).

    Args:
        user_id: ID пользователя.
        db: Сессия БД.
        admin_user: Текущий администратор.

    Raises:
        HTTPException 404: Если пользователь не найден.
    """
    deleted = delete_user(db, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )