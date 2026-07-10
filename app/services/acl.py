"""ACL-сервис: иерархия групп, deny-правила, pre-filtering для Qdrant."""

from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User, UserGroup, user_group_membership
from app.models.document import DocumentGroupPermission


async def get_effective_groups(user_id: int, db: Session) -> list[int]:
    """Получить все группы пользователя с учётом наследования (parent_id).

    Args:
        user_id: ID пользователя.
        db: Сессия БД.

    Returns:
        Список ID групп, включая унаследованные от родительских групп.
    """
    # Прямые группы пользователя
    direct_groups = (
        db.query(UserGroup)
        .join(user_group_membership)
        .filter(user_group_membership.c.user_id == user_id)
        .all()
    )

    # Собираем все группы с учётом наследования
    effective_groups: set[int] = set()
    for group in direct_groups:
        current = group
        while current is not None:
            effective_groups.add(current.id)
            current = current.parent  # поднимаемся по иерархии

    return list(effective_groups)


async def check_access(
    user_id: int,
    document_id: int,
    db: Session,
    permission: str = "read",
) -> bool:
    """Проверить, имеет ли пользователь доступ к документу.

    Правила:
    1. Deny-правила имеют высший приоритет.
    2. Allow-правила разрешают доступ.
    3. Если правил нет — ACL_DEFAULT_DENY.

    Args:
        user_id: ID пользователя.
        document_id: ID документа.
        db: Сессия БД.
        permission: Требуемое право (read, write, admin).

    Returns:
        True если доступ разрешён, False если запрещён.
    """
    from app.core.config import ACL_DEFAULT_DENY

    user_groups = await get_effective_groups(user_id, db)

    rules = (
        db.query(DocumentGroupPermission)
        .filter(DocumentGroupPermission.document_id == document_id)
        .all()
    )

    if not rules:
        return not ACL_DEFAULT_DENY

    # Deny-правила имеют высший приоритет
    for rule in rules:
        if rule.is_deny and rule.group_id in user_groups:
            return False

    # Allow-правила
    for rule in rules:
        if not rule.is_deny and rule.group_id in user_groups:
            return True

    return False


def get_allowed_group_ids(document_id: int, db: Session) -> list[int]:
    """Получить список ID групп, которым разрешён доступ к документу.

    Используется для pre-filtering в Qdrant.

    Args:
        document_id: ID документа.
        db: Сессия БД.

    Returns:
        Список ID групп с разрешённым доступом.
    """
    rules = (
        db.query(DocumentGroupPermission)
        .filter(
            DocumentGroupPermission.document_id == document_id,
            DocumentGroupPermission.is_deny == False,  # noqa: E712
        )
        .all()
    )

    return list(set(rule.group_id for rule in rules))


def get_denied_group_ids(document_id: int, db: Session) -> list[int]:
    """Получить список ID групп, которым запрещён доступ к документу."""
    rules = (
        db.query(DocumentGroupPermission)
        .filter(
            DocumentGroupPermission.document_id == document_id,
            DocumentGroupPermission.is_deny == True,  # noqa: E712
        )
        .all()
    )

    return list(set(rule.group_id for rule in rules))


def build_qdrant_filter(user_groups: list[int]) -> dict:
    """Построить фильтр для Qdrant на основе групп пользователя.

    Qdrant будет искать только те чанки, у которых в payload.allowed_groups
    есть хотя бы одна группа из списка user_groups.

    Args:
        user_groups: Список ID групп пользователя (с учётом наследования).

    Returns:
        Словарь с фильтром для Qdrant search API.
    """
    return {
        "must": [
            {
                "key": "allowed_groups",
                "match": {
                    "any": user_groups,
                },
            }
        ],
    }