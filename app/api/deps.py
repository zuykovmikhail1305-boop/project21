"""FastAPI зависимости: аутентификация, группы доступа, БД."""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.models.user import User
from app.services.acl import get_effective_groups

security = HTTPBearer()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Получить текущего пользователя из JWT токена.

    TODO: Реализовать полноценную проверку JWT токена.
    Для MVP возвращает пользователя с ID=1.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # TODO: Декодировать JWT, извлечь user_id
    # payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    # user_id = payload.get("sub")

    user = db.query(User).filter(User.id == 1).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


async def get_current_user_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[int]:
    """Получить список ID групп текущего пользователя (с учётом наследования)."""
    return await get_effective_groups(current_user.id, db)