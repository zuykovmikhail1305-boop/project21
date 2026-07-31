"""CRUD операции для документов, чанков, папок и ACL."""

from typing import Optional
from sqlalchemy.orm import Session
from app.models.document import (
    Document,
    DocumentChunk,
    DocumentGroupPermission,
    DocumentStatus,
    Folder,
)


# === Folders ===

def create_folder(db: Session, name: str, parent_id: Optional[int] = None) -> Folder:
    """Создать папку."""
    folder = Folder(name=name, parent_id=parent_id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def get_folder(db: Session, folder_id: int) -> Optional[Folder]:
    """Получить папку по ID."""
    return db.query(Folder).filter(Folder.id == folder_id).first()


def list_folders(db: Session, parent_id: Optional[int] = None) -> list[Folder]:
    """Список папок."""
    query = db.query(Folder)
    if parent_id is not None:
        query = query.filter(Folder.parent_id == parent_id)
    else:
        query = query.filter(Folder.parent_id.is_(None))
    return query.all()


# === Documents ===

def create_document(
    db: Session,
    filename: str,
    filepath: str,
    mime_type: str,
    file_size: int,
    uploaded_by: int,
    folder_id: Optional[int] = None,
    storage_path: Optional[str] = None,
) -> Document:
    """Создать запись о документе."""
    doc = Document(
        filename=filename,
        filepath=filepath,
        mime_type=mime_type,
        file_size=file_size,
        uploaded_by=uploaded_by,
        folder_id=folder_id,
        storage_path=storage_path,
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, document_id: int) -> Optional[Document]:
    """Получить документ по ID."""
    return db.query(Document).filter(Document.id == document_id).first()


def list_documents(
    db: Session,
    folder_id: Optional[int] = None,
    status: Optional[DocumentStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Document]:
    """Список документов с фильтрацией."""
    query = db.query(Document)
    if folder_id is not None:
        query = query.filter(Document.folder_id == folder_id)
    if status is not None:
        query = query.filter(Document.status == status)
    return query.offset(skip).limit(limit).all()


def update_document_status(
    db: Session,
    document_id: int,
    status: DocumentStatus,
    error_message: Optional[str] = None,
) -> Document:
    """Обновить статус документа."""
    doc = get_document(db, document_id)
    if doc:
        doc.status = status
        if error_message:
            doc.error_message = error_message
        db.commit()
        db.refresh(doc)
    return doc


def delete_document(db: Session, document_id: int) -> bool:
    """Удалить документ."""
    doc = get_document(db, document_id)
    if doc:
        db.delete(doc)
        db.commit()
        return True
    return False


# === Document Chunks ===

def create_chunk(
    db: Session,
    document_id: int,
    chunk_index: int,
    content: str,
    chunk_type: str = "text",
    metadata: Optional[dict] = None,
    token_count: int = 0,
    vector_id: Optional[str] = None,
) -> DocumentChunk:
    """Создать чанк документа."""
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
    db.commit()
    db.refresh(chunk)
    return chunk


def get_chunks_by_document(db: Session, document_id: int) -> list[DocumentChunk]:
    """Получить все чанки документа."""
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )


def delete_chunks_by_document(db: Session, document_id: int) -> None:
    """Удалить все чанки документа."""
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    db.commit()


# === ACL (Document Group Permissions) ===

def set_document_permission(
    db: Session,
    document_id: int,
    group_id: int,
    permission: str = "read",
    is_deny: bool = False,
) -> DocumentGroupPermission:
    """Установить правило доступа для документа."""
    perm = DocumentGroupPermission(
        document_id=document_id,
        group_id=group_id,
        permission=permission,
        is_deny=is_deny,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


def get_document_permissions(db: Session, document_id: int) -> list[DocumentGroupPermission]:
    """Получить все правила доступа для документа."""
    return (
        db.query(DocumentGroupPermission)
        .filter(DocumentGroupPermission.document_id == document_id)
        .all()
    )


def clear_document_permissions(db: Session, document_id: int) -> None:
    """Очистить все правила доступа для документа."""
    db.query(DocumentGroupPermission).filter(
        DocumentGroupPermission.document_id == document_id
    ).delete()
    db.commit()