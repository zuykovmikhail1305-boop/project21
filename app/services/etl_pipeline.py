"""ETL пайплайн: загрузка → парсинг → чанкинг → эмбеддинги → Qdrant + PostgreSQL.

Асинхронная версия. CPU-bound операции (парсинг, чанкинг, эмбеддинг)
выполняются в thread pool через run_in_executor, чтобы не блокировать event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import AsyncDatabaseSession, QDRANT_COLLECTION_NAME
from app.crud.async_crud_document import (
    async_get_document,
    async_update_document_status,
    async_delete_chunks_by_document,
    async_create_chunk,
)
from app.models.document import DocumentStatus
from app.services.parser import AsyncDocumentParser
from app.services.chunker import AsyncTextChunker
from app.services.embedder import AsyncEmbedder
from app.services.vector_store import AsyncVectorStore

logger = logging.getLogger(__name__)


class ETLPipeline:
    """Асинхронный ETL-пайплайн для обработки документов.

    Выполняет полный цикл: парсинг → чанкинг → эмбеддинги → Qdrant → PostgreSQL.
    """

    def __init__(self) -> None:
        self.parser = AsyncDocumentParser()
        self.chunker = AsyncTextChunker()
        self.embedder = AsyncEmbedder()
        self.vector_store = AsyncVectorStore()

    async def process_document(self, document_id: int) -> None:
        """Обработать документ: парсинг → чанкинг → эмбеддинги → сохранение.

        Args:
            document_id: ID документа в БД.
        """
        async with AsyncDatabaseSession() as db:
            try:
                # 1. Получаем документ из БД
                doc = await async_get_document(db, document_id)
                if not doc:
                    logger.error(f"Document {document_id} not found in DB")
                    return

                logger.info(f"Processing document {document_id}: {doc.filename}")

                # 2. Статус: PROCESSING
                await async_update_document_status(db, document_id, DocumentStatus.PROCESSING)
                logger.info(f"Status set to PROCESSING for doc {document_id}")

                # 3. Парсинг + чанкинг (CPU-bound, в thread pool)
                loop = asyncio.get_event_loop()

                logger.info(f"Parsing file: {doc.filepath}")
                parsed_elements = await self.parser.parse(doc.filepath, document_id)
                logger.info(f"Parsed {len(parsed_elements)} elements")

                # Собираем текст из распарсенных элементов для чанкинга
                # Чанкер сам вызовет parsing внутри, но мы передаём original_path
                logger.info(f"Chunking document {document_id}")
                chunks = await self.chunker.chunk_file(
                    file_path=doc.filepath,
                    doc_id=document_id,
                )
                logger.info(f"Created {len(chunks)} chunks")

                if not chunks:
                    logger.warning(f"No chunks created for document {document_id}")
                    await async_update_document_status(
                        db, document_id, DocumentStatus.READY,
                        "No chunks were created from the document",
                    )
                    return

                # 4. Эмбеддинги (CPU-bound, в thread pool)
                logger.info(f"Generating embeddings for {len(chunks)} chunks")
                texts = [chunk["text"] for chunk in chunks]
                embeddings = await self.embedder.embed_batch(texts)
                logger.info(f"Generated {len(embeddings)} embeddings, size={len(embeddings[0]) if embeddings else 0}")

                # 5. Сохранение в Qdrant (async I/O)
                logger.info(f"Saving to Qdrant collection: {QDRANT_COLLECTION_NAME}")
                points = []
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    point = self.vector_store.prepare_point(
                        point_id=int(f"{document_id}{i:04d}"),
                        vector=embedding,
                        payload={
                            "document_id": document_id,
                            "chunk_index": i,
                            "text": chunk["text"],
                            "metadata": chunk.get("metadata", {}),
                        },
                    )
                    points.append(point)

                await self.vector_store.upsert_points(points)
                logger.info(f"Saved {len(points)} vectors to Qdrant")

                # 6. Удаляем старые чанки из БД (если переобработка)
                await async_delete_chunks_by_document(db, document_id)

                # 7. Сохраняем метаданные чанков в PostgreSQL
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    await async_create_chunk(
                        db=db,
                        document_id=document_id,
                        chunk_index=i,
                        content=chunk["text"],
                        chunk_type="text",
                        metadata=chunk.get("metadata", {}),
                        token_count=len(chunk["text"].split()),
                        vector_id=f"{document_id}{i:04d}",
                    )
                logger.info(f"Saved {len(chunks)} chunk metadata to DB")

                # 8. Статус: READY
                await async_update_document_status(db, document_id, DocumentStatus.READY)
                logger.info(f"Document {document_id} processed successfully, status=READY")

            except Exception as e:
                logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
                await async_update_document_status(db, document_id, DocumentStatus.ERROR, str(e))
                raise


# Экземпляр пайплайна (singleton) для использования в endpoint'ах
etl_pipeline = ETLPipeline()


async def process_document(document_id: int) -> None:
    """Convenience function: process a document using the singleton pipeline.

    Args:
        document_id: ID документа в БД.
    """
    await etl_pipeline.process_document(document_id)
