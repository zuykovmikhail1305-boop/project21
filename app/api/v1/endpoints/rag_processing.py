"""API эндпоинты для RAG-обработки: search, answer, hyde, index."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_current_user_groups
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
from app.RAG_Misha.find import Find_answer
from app.RAG_Misha.agent import Agent
from app.services.etl_pipeline import etl_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


def get_Find_answer() -> Find_answer:
    """Dependency: получить инстанс Find_answer."""
    return Find_answer()

def get_Agent() -> Agent:
    """Dependency: получить инстанс Agent."""
    return Agent()


@router.post("/search", response_model=RAGSearchResponse)
async def rag_search(
    request: RAGSearchRequest,
    current_user: User = Depends(get_current_user),
    user_groups: list[int] = Depends(get_current_user_groups),
    rag: Find_answer = Depends(get_Find_answer),
):
    """Поиск релевантных чанков: dense + sparse + HyDE + RRF fusion + rerank.

    Многоэтапный поиск по векторному хранилищу с использованием
    семантического (dense) и BM25-подобного (sparse) поиска,
    HyDE-генерации при недостатке результатов и финального reranking.
    """
    try:
        groups = request.user_groups or user_groups
        chunks = rag.find_answer(
            query=request.query
        )
        return RAGSearchResponse(
            chunks=chunks,
            total=len(chunks),
        )
    except Exception as e:
        logger.exception("RAG search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {e!s}")


@router.post("/index", response_model=RAGIndexResponse)
async def rag_index(
    request: RAGIndexRequest,
    current_user: User = Depends(get_current_user),
):
    """Проиндексировать документ: parsing → chunking → embed → Qdrant + PostgreSQL.

    Асинхронная версия. Использует ETLPipeline с прямым вызовом сервисов
    (без self-вызова через HTTP). CPU-bound операции выполняются в thread pool.

    Args:
        request: RAGIndexRequest с document_id.
    """
    try:
        if request.document_id is None:
            return RAGIndexResponse(
                status="error",
                message="document_id is required",
            )

        await etl_pipeline.process_document(request.document_id)
        return RAGIndexResponse(
            status="ok",
            message=f"Document {request.document_id} indexed successfully",
        )
    except Exception as e:
        logger.exception("RAG index failed")
        return RAGIndexResponse(
            status="error",
            message=f"Index failed: {e!s}",
        )
