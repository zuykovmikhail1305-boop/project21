"""ETL пайплайн: загрузка → парсинг → чанкинг → эмбеддинги → Qdrant + PostgreSQL."""

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
from app.services.rag_service import GigaChatRAGService

logger = logging.getLogger(__name__)


def process_document(document_id: int) -> None:
    """Обработать документ: парсинг → чанкинг → эмбеддинги → сохранение.

    Запускается в фоновой задаче (BackgroundTasks).
    """
    db: Session = next(get_db())

    try:
        doc = get_document(db, document_id)
        if not doc:
            logger.error(f"Document {document_id} not found")
            return

        # 1. Статус: PROCESSING
        update_document_status(db, document_id, DocumentStatus.PROCESSING)
        logger.info(f"Processing document {document_id}: {doc.filename}")

        # 2. Используем новый RAG-сервис для индексирования документа
        rag_service = GigaChatRAGService()
        points = rag_service.index_document(doc.filepath)
        logger.info(f"Indexed {len(points)} chunks for {doc.filename}")

        # 3. Удаляем старые чанки (если переобработка)
        delete_chunks_by_document(db, document_id)

        # 4. Сохраняем метаданные чанков в PostgreSQL
        for point in points:
            payload = point.get("payload", {})
            create_chunk(
                db=db,
                document_id=document_id,
                chunk_index=payload.get("chunk_index", 0),
                content=payload.get("content", ""),
                chunk_type=payload.get("chunk_type", "text"),
                metadata=payload.get("metadata", {}),
                token_count=0,
                vector_id=str(point.get("id", "")),
            )

        # 6. Статус: READY
        update_document_status(db, document_id, DocumentStatus.READY)
        logger.info(f"Document {document_id} processed successfully")

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
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
