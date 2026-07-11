"""CRUD операции для модели User."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Получить пользователя по email.

    Args:
        db: Сессия БД.
        email: Email пользователя.

    Returns:
        User или None, если не найден.
    """
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Получить пользователя по ID.

    Args:
        db: Сессия БД.
        user_id: ID пользователя.

    Returns:
        User или None, если не найден.
    """
    return db.query(User).filter(User.id == user_id).first()


def create_user(
    db: Session,
    email: str,
    username: str,
    hashed_password: str,
) -> User:
    """Создать нового пользователя.

    Args:
        db: Сессия БД.
        email: Email пользователя.
        username: Имя пользователя.
        hashed_password: Хеш пароля.

    Returns:
        Созданный объект User.
    """
    user = User(
        email=email,
        username=username,
        hashed_password=hashed_password,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_users(
    db: Session,
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    """Получить список пользователей с пагинацией.

    Args:
        db: Сессия БД.
        skip: Смещение.
        limit: Лимит записей.

    Returns:
        Список пользователей.
    """
    return db.query(User).offset(skip).limit(limit).all()


def update_user(
    db: Session,
    user_id: int,
    **kwargs,
) -> Optional[User]:
    """Обновить данные пользователя.

    Args:
        db: Сессия БД.
        user_id: ID пользователя.
        **kwargs: Поля для обновления.

    Returns:
        Обновлённый User или None, если не найден.
    """
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    for key, value in kwargs.items():
        if hasattr(user, key):
            setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    """Удалить пользователя.

    Args:
        db: Сессия БД.
        user_id: ID пользователя.

    Returns:
        True если удалён, False если не найден.
    """
    user = get_user_by_id(db, user_id)
    if not user:
        return False

    db.delete(user)
    db.commit()
    return True