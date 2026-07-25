"""ETL пайплайн: загрузка → парсинг → чанкинг → эмбеддинги → Qdrant + PostgreSQL.

Выполняет индексацию документа через RAG API (HTTP-клиент RAGClient)
вместо прямого вызова GigaChatRAGService.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_db, QDRANT_COLLECTION_NAME
from app.core.dependencies import get_qdrant_client, get_embedder
from app.crud.crud_document import (
    get_document,
    update_document_status,
    create_chunk,
    delete_chunks_by_document,
    get_document_permissions,
)
from app.models.document import DocumentStatus
from app.services.rag_client import RAGClient

logger = logging.getLogger(__name__)


def process_document(document_id: int, token: Optional[str] = None) -> None:
    """Обработать документ: парсинг → чанкинг → эмбеддинги → сохранение.

    Запускается в фоновой задаче (BackgroundTasks).
    Использует RAGClient для вызова API индексации.

    Args:
        document_id: ID документа в БД.
        token: JWT-токен для аутентификации (сервисный/админский).
    """
    import traceback
    db: Session = next(get_db())

    try:
        doc = get_document(db, document_id)
        if not doc:
            logger.error(f"=== ETL DEBUG: Document {document_id} not found in DB")
            return

        logger.info(f"=== ETL DEBUG: Starting processing for doc {document_id}")
        logger.info(f"=== ETL DEBUG: filename={doc.filename}, filepath={doc.filepath}")
        logger.info(f"=== ETL DEBUG: filepath exists on disk: {__import__('os').path.exists(doc.filepath)}")

        # 1. Статус: PROCESSING
        update_document_status(db, document_id, DocumentStatus.PROCESSING)
        logger.info(f"=== ETL DEBUG: Status set to PROCESSING for doc {document_id}")

        # 2. Индексация через RAG API
        logger.info(f"=== ETL DEBUG: Creating RAGClient...")
        rag_client = RAGClient(token=token or "")
        logger.info(f"=== ETL DEBUG: Calling index_document via RAG API for filepath={doc.filepath}, document_id={document_id}")
        points = rag_client.index_document(
            file_path=str(doc.filepath),
            document_id=document_id,
        )
        logger.info(f"=== ETL DEBUG: Indexed document via RAG API for {doc.filename}")

        # 3. Удаляем старые чанки (если переобработка)
        delete_chunks_by_document(db, document_id)
        logger.info(f"=== ETL DEBUG: Old chunks deleted for doc {document_id}")

        # 4. Сохраняем метаданные чанков в PostgreSQL
        # NOTE: RAGClient.index_document() возвращает пустой список,
        # так как API не возвращает полные точки.
        # Метаданные чанков сохраняются в БД через callback или отдельный эндпоинт.
        # Пока пропускаем этот шаг — он будет доработан отдельно.
        logger.info(f"=== ETL DEBUG: Chunk metadata saving skipped (will be added later)")

        # 6. Статус: READY
        update_document_status(db, document_id, DocumentStatus.READY)
        logger.info(f"=== ETL DEBUG: Document {document_id} processed successfully, status=READY")

    except Exception as e:
        logger.error(f"=== ETL DEBUG: Error processing document {document_id}: {e}")
        logger.error(traceback.format_exc())
        update_document_status(db, document_id, DocumentStatus.ERROR, str(e))
        raise

    finally:
        db.close()


def _ensure_qdrant_collection(qdrant_client, vector_size: int) -> None:
    """Создать коллекцию в Qdrant, если её нет."""
    from qdrant_client.http.exceptions import UnexpectedResponse

    try:
        collections = qdrant_client.get_collections().collections
        exists = any(c.name == QDRANT_COLLECTION_NAME for c in collections)

        if not exists:
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION_NAME,
                vectors_config={
                    "size": vector_size,
                    "distance": "Cosine",
                },
            )
            logger.info(f"Created Qdrant collection: {QDRANT_COLLECTION_NAME}")
    except UnexpectedResponse as e:
        logger.warning(f"Qdrant not available yet: {e}")
