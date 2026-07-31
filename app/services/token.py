"""TokenService: создание, обновление и отзыв JWT токенов."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.user import RefreshToken, User


class TokenService:
    """Сервис для управления JWT токенами.

    Access token: короткоживущий (30 мин по умолчанию).
    Refresh token: долгоживущий (7 дней), хранится в БД для возможности отзыва.
    """

    def __init__(self, db: Session):
        self.db = db

    async def create_tokens(self, user_id: int) -> dict[str, str]:
        """Создать пару access + refresh токенов.

        Args:
            user_id: ID пользователя.

        Returns:
            Словарь с access_token и refresh_token.
        """
        # Access token
        access_token = create_access_token(data={"sub": str(user_id)})

        # Refresh token с уникальным jti
        jti = str(uuid.uuid4())
        refresh_token = create_refresh_token(data={"sub": str(user_id), "jti": jti})

        # Сохраняем хеш refresh token в БД
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        db_refresh = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(db_refresh)
        self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def refresh_tokens(self, refresh_token_str: str) -> Optional[dict[str, str]]:
        """Обновить пару токенов по refresh token (token rotation).

        Старый refresh token помечается как revoked.
        Новый refresh token сохраняется в БД.

        Args:
            refresh_token_str: Refresh token string.

        Returns:
            Словарь с новыми access_token и refresh_token, или None если токен невалиден.
        """
        # Декодируем токен
        try:
            payload = decode_token(refresh_token_str)
        except JWTError:
            return None

        # Проверяем тип токена
        if payload.get("type") != "refresh":
            return None

        jti: Optional[str] = payload.get("jti")
        sub: Optional[str] = payload.get("sub")

        if not jti or not sub:
            return None

        user_id = int(sub)

        # Находим запись в БД по хешу
        token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
        db_token = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == user_id,
            )
            .first()
        )

        if not db_token:
            return None

        # Проверяем не отозван ли и не истёк ли
        if bool(db_token.revoked):
            return None

        if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None

        # Отзываем старый токен (rotation)
        db_token.revoked = True  # type: ignore[assignment]
        self.db.commit()

        # Создаём новую пару
        return await self.create_tokens(user_id)

    async def revoke_refresh_token(self, refresh_token_str: str) -> bool:
        """Отозвать refresh token (logout).

        Args:
            refresh_token_str: Refresh token string.

        Returns:
            True если успешно отозван, False если не найден.
        """
        token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
        db_token = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )

        if not db_token:
            return False

        db_token.revoked = True  # type: ignore[assignment]
        self.db.commit()
        return True

    async def revoke_all_user_tokens(self, user_id: int) -> int:
        """Отозвать все refresh токены пользователя.

        Используется при смене пароля или блокировке пользователя.

        Args:
            user_id: ID пользователя.

        Returns:
            Количество отозванных токенов.
        """
        result = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,  # noqa: E712
            )
            .update({"revoked": True})
        )
        self.db.commit()
        return result

    async def cleanup_expired_tokens(self) -> int:
        """Очистить истёкшие refresh токены.

        Returns:
            Количество удалённых записей.
        """
        result = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.expires_at < datetime.now(timezone.utc))
            .delete()
        )
        self.db.commit()
        return result