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
from app.services.parser import parse_document
from app.services.chunker import chunk_document

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

        # 2. Парсинг
        parse_result = parse_document(doc.filepath)
        logger.info(f"Parsed {doc.filename}: {len(parse_result.text)} chars")

        # 3. Чанкинг
        chunks = chunk_document(
            text=parse_result.text,
            metadata=parse_result.metadata,
        )
        logger.info(f"Created {len(chunks)} chunks for {doc.filename}")

        # 4. Удаляем старые чанки (если переобработка)
        delete_chunks_by_document(db, document_id)

        # 5. Генерация эмбеддингов и сохранение
        embedder = get_embedder()
        qdrant = get_qdrant_client()

        # Получаем ACL правила для документа
        permissions = get_document_permissions(db, document_id)
        allowed_groups = list(set(p.group_id for p in permissions if not p.is_deny))

        # Создаём коллекцию в Qdrant, если её нет
        _ensure_qdrant_collection(qdrant, embedder.vector_size)

        # Сохраняем чанки
        for chunk in chunks:
            # Генерируем эмбеддинг
            embedding = embedder.embed(chunk.content)

            # Сохраняем в Qdrant
            point_id = qdrant.upsert(
                collection_name=QDRANT_COLLECTION_NAME,
                points=[{
                    "vector": embedding,
                    "payload": {
                        "document_id": document_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "chunk_type": chunk.chunk_type,
                        "metadata": chunk.metadata,
                        "allowed_groups": allowed_groups,
                    },
                }],
            )

            # Сохраняем в PostgreSQL
            vector_id = str(point_id[0].uuid) if hasattr(point_id[0], 'uuid') else str(point_id[0])
            create_chunk(
                db=db,
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                chunk_type=chunk.chunk_type,
                metadata=chunk.metadata,
                token_count=chunk.token_count,
                vector_id=vector_id,
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