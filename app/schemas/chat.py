"""Pydantic схемы для API: чаты."""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ChatSessionResponse(BaseModel):
    """Схема ответа с данными сессии чата."""
    id: int
    title: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    """Схема ответа с данными сообщения."""
    id: int
    role: str
    content: str
    citations: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """Схема запроса на отправку сообщения в чат."""
    session_id: Optional[int] = None
    message: str


class ChatCreateResponse(BaseModel):
    """Схема ответа при создании новой сессии."""
    session_id: int
    title: str = "Новый чат"