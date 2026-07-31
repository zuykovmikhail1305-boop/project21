"""Async CRUD операции для документов, чанков и папок.

Использует AsyncSession вместо Session для асинхронной работы.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import (
    Document,
    DocumentChunk,
    DocumentGroupPermission,
    DocumentStatus,
    Folder,
)

logger = logging.getLogger(__name__)


# ─── Folders ────────────────────────────────────────────────────────────────

async def async_create_folder(
    db: AsyncSession,
    name: str,
    parent_id: int | None = None,
) -> Folder:
    """Create a new folder."""
    folder = Folder(name=name, parent_id=parent_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


async def async_get_folder(
    db: AsyncSession,
    folder_id: int,
) -> Folder | None:
    """Get folder by ID."""
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    return result.scalars().first()


async def async_list_folders(
    db: AsyncSession,
    parent_id: int | None = None,
) -> list[Folder]:
    """List folders, optionally filtered by parent_id."""
    stmt = select(Folder)
    if parent_id is not None:
        stmt = stmt.where(Folder.parent_id == parent_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─── Documents ──────────────────────────────────────────────────────────────

async def async_create_document(
    db: AsyncSession,
    filename: str,
    filepath: str,
    mime_type: str,
    file_size: int,
    uploaded_by: int,
    folder_id: int | None = None,
    storage_path: str | None = None,
) -> Document:
    """Create a new document record."""
    doc = Document(
        filename=filename,
        filepath=filepath,
        mime_type=mime_type,
        file_size=file_size,
        uploaded_by=uploaded_by,
        folder_id=folder_id,
        storage_path=storage_path,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def async_get_document(
    db: AsyncSession,
    document_id: int,
) -> Document | None:
    """Get document by ID."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalars().first()


async def async_list_documents(
    db: AsyncSession,
    folder_id: int | None = None,
    status: DocumentStatus | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Document]:
    """List documents with optional filters."""
    stmt = select(Document)
    if folder_id is not None:
        stmt = stmt.where(Document.folder_id == folder_id)
    if status is not None:
        stmt = stmt.where(Document.status == status)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def async_update_document_status(
    db: AsyncSession,
    document_id: int,
    status: DocumentStatus,
    error_message: str | None = None,
) -> Document:
    """Update document status (and optionally error message)."""
    doc = await async_get_document(db, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found")
    doc.status = status
    if error_message is not None:
        doc.error_message = error_message
    await db.commit()
    await db.refresh(doc)
    return doc


async def async_delete_document(
    db: AsyncSession,
    document_id: int,
) -> bool:
    """Delete a document by ID."""
    doc = await async_get_document(db, document_id)
    if doc is None:
        return False
    await db.delete(doc)
    await db.commit()
    return True


# ─── Document Chunks ────────────────────────────────────────────────────────

async def async_create_chunk(
    db: AsyncSession,
    document_id: int,
    chunk_index: int,
    content: str,
    chunk_type: str = "text",
    metadata: dict | None = None,
    token_count: int = 0,
    vector_id: str | None = None,
) -> DocumentChunk:
    """Create a new document chunk."""
    chunk = DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        content=content,
        chunk_type=chunk_type,
        chunk_metadata=metadata or {},
        token_count=token_count,
        vector_id=vector_id,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return chunk


async def async_get_chunks_by_document(
    db: AsyncSession,
    document_id: int,
) -> list[DocumentChunk]:
    """Get all chunks for a document."""
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def async_delete_chunks_by_document(
    db: AsyncSession,
    document_id: int,
) -> None:
    """Delete all chunks for a document."""
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    await db.commit()


# ─── ACL / Permissions ──────────────────────────────────────────────────────

async def async_set_document_permission(
    db: AsyncSession,
    document_id: int,
    group_id: int,
    permission: str = "read",
    is_deny: bool = False,
) -> DocumentGroupPermission:
    """Set a permission for a group on a document."""
    perm = DocumentGroupPermission(
        document_id=document_id,
        group_id=group_id,
        permission=permission,
        is_deny=is_deny,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    return perm


async def async_get_document_permissions(
    db: AsyncSession,
    document_id: int,
) -> list[DocumentGroupPermission]:
    """Get all permissions for a document."""
    result = await db.execute(
        select(DocumentGroupPermission).where(DocumentGroupPermission.document_id == document_id)
    )
    return list(result.scalars().all())


async def async_clear_document_permissions(
    db: AsyncSession,
    document_id: int,
) -> None:
    """Clear all permissions for a document."""
    await db.execute(
        delete(DocumentGroupPermission).where(DocumentGroupPermission.document_id == document_id)
    )
    await db.commit()