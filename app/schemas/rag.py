"""Pydantic схемы для RAG API: search, answer, hyde, index."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# === Search ===


class RAGSearchRequest(BaseModel):
    """Запрос на поиск релевантных чанков."""

    query: str = Field(..., description="Поисковый запрос")
    user_groups: list[int] = Field(
        default_factory=list, description="Список ID групп пользователя (для ACL)"
    )
    top_k: int = Field(20, description="Количество результатов поиска", ge=1, le=100)
    history: Optional[list[dict]] = Field(
        None, description="История диалога для HyDE (список словарей с ключами 'role' и 'content')"
    )


class RAGSearchResponse(BaseModel):
    """Результат поиска релевантных чанков."""

    chunks: list[dict] = Field(default_factory=list, description="Найденные чанки с метаданными")
    total: int = Field(0, description="Общее количество найденных чанков")


# === Answer ===


class RAGAnswerRequest(BaseModel):
    """Запрос на получение ответа на вопрос с контекстом из документов."""

    query: str = Field(..., description="Вопрос пользователя")
    user_groups: list[int] = Field(
        default_factory=list, description="Список ID групп пользователя (для ACL)"
    )
    top_k: int = Field(5, description="Количество чанков для поиска", ge=1, le=50)
    history: Optional[list[dict]] = Field(
        None, description="История диалога для HyDE (список словарей с ключами 'role' и 'content')"
    )


class RAGAnswerResponse(BaseModel):
    """Ответ на вопрос пользователя на основе найденных документов."""

    answer: str = Field("", description="Сгенерированный ответ")
    confidence: float = Field(0.0, description="Уверенность в ответе от 0.0 до 1.0")
    citations: list[dict] = Field(
        default_factory=list, description="Список цитат (document_id, chunk_index, score)"
    )
    chunks: list[dict] = Field(
        default_factory=list, description="Найденные чанки с метаданными"
    )


# === HyDE ===


class RAGHydeRequest(BaseModel):
    """Запрос на генерацию HyDE (гипотетического документа для поиска)."""

    query: str = Field(..., description="Запрос пользователя")
    history: Optional[list[dict]] = Field(
        None, description="История диалога (список словарей с ключами 'role' и 'content')"
    )
    split_chunks: bool = Field(True, description="Если True — разбить на чанки для множественного поиска")
    max_chunks: int = Field(5, description="Максимальное количество чанков", ge=1, le=20)


class RAGHydeResponse(BaseModel):
    """Результат генерации HyDE."""

    chunks: list[str] = Field(default_factory=list, description="Список текстовых чанков HyDE-документа")


# === Index ===


class RAGIndexRequest(BaseModel):
    """Запрос на индексацию документа в Qdrant."""

    file_path: str = Field(..., description="Путь к файлу документа")
    document_id: Optional[int] = Field(None, description="ID документа в БД (для ACL)")


class RAGIndexResponse(BaseModel):
    """Результат индексации документа."""

    status: str = Field("ok", description="Статус операции: ok / error")
    points_count: int = Field(0, description="Количество сохранённых точек в Qdrant")
    message: str = Field("", description="Сообщение о результате операции")