"""Pydantic схемы для API: пользователи и группы."""

from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    """Базовая схема пользователя."""
    username: str
    email: str


class UserCreate(UserBase):
    """Схема создания пользователя."""
    password: str


class UserResponse(UserBase):
    """Схема ответа с данными пользователя."""
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserGroupResponse(BaseModel):
    """Схема ответа с данными группы."""
    id: int
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    priority: int = 0

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Схема ответа с JWT токеном."""
    access_token: str
    token_type: str = "bearer"
