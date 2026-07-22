"""FastAPI зависимости: аутентификация, группы доступа, БД.

Поддерживает два способа передачи JWT:
1. HTTP Header: Authorization: Bearer <token> (для API-клиентов / fetch)
2. Cookie: access_token=<token> (для HTML-страниц при навигации)
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.core.security import decode_token
from app.crud.crud_user import get_user_by_id
from app.models.user import User, UserGroup
from app.services.acl import get_effective_groups


def _extract_token(request: Request) -> Optional[str]:
    """Извлечь JWT токен из заголовка Authorization или cookie.

    Приоритет: Authorization header > cookie.
    Это позволяет API-клиентам работать через header,
    а HTML-страницам получать токен через cookie.

    Args:
        request: HTTP запрос.

    Returns:
        Строка токена или None.
    """
    # 1. Пробуем Authorization header (для API-запросов из JS)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 2. Пробуем cookie (для HTML-страниц при навигации)
    token = request.cookies.get("access_token")
    if token:
        return token

    return None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Получить текущего пользователя из JWT access token.

    Декодирует JWT из Authorization header или cookie,
    извлекает user_id из payload.sub,
    проверяет что пользователь существует и активен.

    Args:
        request: HTTP запрос (для извлечения токена из header/cookie).
        db: Сессия БД.

    Returns:
        Объект User.

    Raises:
        HTTPException 401: Если токен невалиден, истёк, или пользователь не найден/неактивен.
    """
    token = _extract_token(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Проверяем тип токена — должен быть access
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Use access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Извлекаем user_id
    user_id_str: Optional[str] = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Получаем пользователя из БД
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not bool(user.is_active):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_user_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[int]:
    """Получить список ID групп текущего пользователя (с учётом наследования).

    Args:
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        Список ID групп.
    """
    return await get_effective_groups(current_user.id, db)  # type: ignore[arg-type]


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Проверить, что текущий пользователь является администратором.

    Args:
        current_user: Текущий пользователь (из JWT).
        db: Сессия БД.

    Returns:
        Объект User если пользователь администратор.

    Raises:
        HTTPException 403: Если пользователь не в группе admins.
    """
    admin_group = db.query(UserGroup).filter(UserGroup.name == "admins").first()
    if not admin_group:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin group not found",
        )

    user_groups = await get_effective_groups(current_user.id, db)  # type: ignore[arg-type]
    if admin_group.id not in user_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    return current_user