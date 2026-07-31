"""UserService: регистрация, аутентификация, управление группами."""

from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.crud.crud_user import create_user, get_user_by_email, get_user_by_id
from app.models.user import User, UserGroup, user_group_membership


class UserService:
    """Сервис для операций с пользователями."""

    def __init__(self, db: Session):
        self.db = db

    async def register(
        self,
        email: str,
        username: str,
        password: str,
    ) -> User:
        """Зарегистрировать нового пользователя.

        Args:
            email: Email пользователя.
            username: Имя пользователя.
            password: Пароль (plain-text).

        Returns:
            Созданный объект User.

        Raises:
            ValueError: Если email уже занят.
        """
        # Проверка уникальности email
        existing = get_user_by_email(self.db, email)
        if existing:
            raise ValueError(f"User with email '{email}' already exists")

        # Хеширование пароля
        hashed = hash_password(password)

        # Создание пользователя
        user = create_user(self.db, email=email, username=username, hashed_password=hashed)

        # Добавление в группу "users" по умолчанию
        await self.add_to_default_group(user)

        return user

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Аутентифицировать пользователя по email и паролю.

        Args:
            email: Email пользователя.
            password: Пароль (plain-text).

        Returns:
            User если аутентификация успешна, None если нет.
        """
        user = get_user_by_email(self.db, email)
        if not user:
            return None
        if not bool(user.is_active):
            return None
        if not verify_password(password, str(user.hashed_password)):
            return None
        return user

    async def add_to_default_group(self, user: User) -> None:
        """Добавить пользователя в группу 'users' по умолчанию.

        Args:
            user: Объект пользователя.
        """
        users_group = self.db.query(UserGroup).filter(UserGroup.name == "users").first()
        if users_group and users_group not in user.groups:
            user.groups.append(users_group)
            self.db.commit()

    async def add_to_admin_group(self, user: User) -> None:
        """Добавить пользователя в группу 'admins'.

        Args:
            user: Объект пользователя.
        """
        admin_group = self.db.query(UserGroup).filter(UserGroup.name == "admins").first()
        if admin_group and admin_group not in user.groups:
            user.groups.append(admin_group)
            self.db.commit()

    async def is_admin(self, user: User) -> bool:
        """Проверить, является ли пользователь администратором.

        Args:
            user: Объект пользователя.

        Returns:
            True если пользователь в группе admins.
        """
        admin_group = self.db.query(UserGroup).filter(UserGroup.name == "admins").first()
        if not admin_group:
            return False
        return admin_group in user.groups

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID.

        Args:
            user_id: ID пользователя.

        Returns:
            User или None.
        """
        return get_user_by_id(self.db, user_id)