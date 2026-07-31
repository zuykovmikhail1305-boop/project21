"""Security utilities: password hashing (Argon2), JWT creation and verification."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from passlib.context import CryptContext
from jose import JWTError, jwt

from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    # argon2 defaults (OWASP recommended):
    #   time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16
)


# ===================== Password Hashing =====================


def hash_password(password: str) -> str:
    """Hash a plain-text password using Argon2.

    Args:
        password: Plain-text password (no length limit).

    Returns:
        Argon2 hash string.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against an Argon2 hash.

    Args:
        plain_password: Plain-text password to verify.
        hashed_password: Stored Argon2 hash.

    Returns:
        True if password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ===================== JWT Tokens =====================


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Payload data (must include 'sub' with user_id).
        expires_delta: Custom expiration time. Defaults to config value.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT refresh token.

    Args:
        data: Payload data (must include 'sub' with user_id and 'jti').
        expires_delta: Custom expiration time. Defaults to 7 days.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=7)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded payload dictionary.

    Raises:
        JWTError: If token is invalid, expired, or signature is wrong.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])