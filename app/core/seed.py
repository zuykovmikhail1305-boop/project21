"""Seed data: предопределённые группы доступа (admins, users)."""

from sqlalchemy.orm import Session

from app.models.user import UserGroup


def seed_groups(db: Session) -> None:
    """Создать предопределённые группы при первом запуске.

    - admins: полный доступ ко всем документам, управление пользователями
    - users: обычные пользователи с ACL на документах

    Вызывается в lifespan startup main.py.
    """
    try:
        if not db.query(UserGroup).filter(UserGroup.name == "admins").first():
            db.add(UserGroup(
                name="admins",
                description="Administrators — full access to all documents and user management",
                priority=100,
            ))

        if not db.query(UserGroup).filter(UserGroup.name == "users").first():
            db.add(UserGroup(
                name="users",
                description="Regular users — access controlled by document ACL",
                priority=0,
            ))

        db.commit()
    except Exception:
        db.rollback()
