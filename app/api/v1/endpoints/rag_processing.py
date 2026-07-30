"""API эндпоинты для RAG-обработки: search, answer, hyde, index."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_groups
from app.core.config import get_db
from app.models.user import User
from app.schemas.rag import (
    RAGAnswerRequest,
    RAGAnswerResponse,
    RAGHydeRequest,
    RAGHydeResponse,
    RAGIndexRequest,
    RAGIndexResponse,
    RAGSearchRequest,
    RAGSearchResponse,
)
from app.RAG_Misha.processing import Processing
from app.RAG_Misha.find import Find_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


def get_Processing(file_path) -> Processing:
    """Dependency: получить инстанс Processing."""
    return Processing()


def get_Find_answer() -> Find_answer:
    """Dependency: получить инстанс Find_answer."""
    return Find_answer()


@router.post("/search", response_model=RAGSearchResponse)
async def rag_search(
    request: RAGSearchRequest,
    current_user: User = Depends(get_current_user),
    user_groups: list[int] = Depends(get_current_user_groups),
    rag: GigaChatRAGService = Depends(get_rag_service),
):
    """Поиск релевантных чанков: dense + sparse + HyDE + RRF fusion + rerank.

    Многоэтапный поиск по векторному хранилищу с использованием
    семантического (dense) и BM25-подобного (sparse) поиска,
    HyDE-генерации при недостатке результатов и финального reranking.
    """
    try:
        # Если user_groups не передан в запросе, используем из JWT
        groups = request.user_groups or user_groups
        chunks = await rag.search(
            query=request.query,
            user_groups=groups,
            top_k=request.top_k,
            history=request.history,
        )
        return RAGSearchResponse(
            chunks=chunks,
            total=len(chunks),
        )
    except Exception as e:
        logger.exception("RAG search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {e!s}")


@router.post("/answer", response_model=RAGAnswerResponse)
async def rag_answer(
    request: RAGAnswerRequest,
    current_user: User = Depends(get_current_user),
    user_groups: list[int] = Depends(get_current_user_groups),
    rag: GigaChatRAGService = Depends(get_rag_service),
):
    """Получить ответ на вопрос на основе найденных документов.

    Выполняет поиск релевантных чанков, затем генерирует ответ
    через LLM на основе найденного контекста.
    """
    try:
        groups = request.user_groups or user_groups
        result = await rag.answer(
            query=request.query,
            user_groups=groups,
            top_k=request.top_k,
            history=request.history,
        )
        return RAGAnswerResponse(
            answer=result.get("answer", ""),
            confidence=result.get("confidence", 0.0),
            citations=result.get("citations", []),
            chunks=result.get("chunks", []),
        )
    except Exception as e:
        logger.exception("RAG answer failed")
        raise HTTPException(status_code=500, detail=f"Answer failed: {e!s}")


@router.post("/hyde", response_model=RAGHydeResponse)
async def rag_hyde(
    request: RAGHydeRequest,
    current_user: User = Depends(get_current_user),
    rag: GigaChatRAGService = Depends(get_rag_service),
):
    """Сгенерировать HyDE (гипотетический документ) для улучшения поиска.

    Использует LLM для генерации гипотетического документа,
    который затем разбивается на чанки для множественного поиска.
    """
    try:
        chunks = await rag.generate_hyde(
            query=request.query,
            history=request.history,
            split_chunks=request.split_chunks,
            max_chunks=request.max_chunks,
        )
        return RAGHydeResponse(chunks=chunks)
    except Exception as e:
        logger.exception("RAG HyDE generation failed")
        raise HTTPException(status_code=500, detail=f"HyDE generation failed: {e!s}")


@router.post("/index", response_model=RAGIndexResponse)
async def rag_index(
    request: RAGIndexRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rag: GigaChatRAGService = Depends(get_rag_service),
):
    """Проиндексировать документ: parsing → chunking → embed → Qdrant.

    Выполняет полный цикл индексации документа:
    1. Парсинг файла через RAG_Misha.processing.Processing
    2. Чанкинг на смысловые блоки
    3. Эмбеддинг каждого чанка
    4. Сохранение в Qdrant с ACL-правилами
    """
    try:
        points = rag.index_document(
            file_path=request.file_path,
            document_id=request.document_id,
            db=db,
        )
        return RAGIndexResponse(
            status="ok",
            points_count=len(points),
            message=f"Document indexed successfully: {len(points)} chunks saved",
        )
    except Exception as e:
        logger.exception("RAG index failed")
        return RAGIndexResponse(
            status="error",
            points_count=0,
            message=f"Index failed: {e!s}",
        )
