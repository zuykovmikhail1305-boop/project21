"""API эндпоинты для работы с документами."""

import os
from typing import Optional
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_db
from app.crud.crud_document import (
    create_document,
    get_document,
    list_documents,
    delete_document,
    update_document_status,
    create_folder,
    list_folders,
)
from app.schemas.document import (
    DocumentResponse,
    DocumentDetailResponse,
    DocumentUploadResponse,
    FolderResponse,
)
from app.models.document import DocumentStatus

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/", response_model=list[DocumentResponse])
async def get_documents(
    folder_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Получить список документов."""
    doc_status = None
    if status:
        try:
            doc_status = DocumentStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    return list_documents(db, folder_id=folder_id, status=doc_status, skip=skip, limit=limit)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(document_id: int, db: Session = Depends(get_db)):
    """Получить детальную информацию о документе."""
    doc = get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    folder_id: Optional[int] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """Загрузить документ."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("=== UPLOAD DEBUG ===")
    logger.info(f"Filename: {file.filename}")
    logger.info(f"Content-Type: {file.content_type}")
    logger.info(f"Folder ID: {folder_id}")

    # Сохраняем файл локально
    upload_dir = "./uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename or "unnamed")
    logger.info(f"Saving to: {file_path}")

    content = await file.read()
    logger.info(f"File size: {len(content)} bytes")

    with open(file_path, "wb") as f:
        f.write(content)
    logger.info(f"File saved successfully, exists: {os.path.exists(file_path)}")

    # Создаём запись в БД
    try:
        doc = create_document(
            db=db,
            filename=file.filename or "unnamed",
            filepath=file_path,
            mime_type=file.content_type or "application/octet-stream",
            file_size=len(content),
            uploaded_by=1,  # TODO: заменить на реального пользователя из JWT
            folder_id=folder_id,
            storage_path=file_path,
        )
        logger.info(f"DB record created: id={doc.id}, status={doc.status}")
    except Exception as e:
        logger.error(f"DB create_document failed: {e}", exc_info=True)
        raise

    # Запускаем ETL-обработку в фоне
    logger.info(f"Adding background task for document {doc.id}")
    background_tasks.add_task(process_document_background, doc.id)

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename or "unnamed",
        status=doc.status.value,
    )


def process_document_background(document_id: int):
    """Фоновая задача: запуск ETL пайплайна."""
    from app.services.etl_pipeline import process_document
    process_document(document_id)


@router.delete("/{document_id}", status_code=204)
async def delete_document_endpoint(document_id: int, db: Session = Depends(get_db)):
    """Удалить документ."""
    if not delete_document(db, document_id):
        raise HTTPException(status_code=404, detail="Document not found")


# === Folders ===

@router.get("/folders/list", response_model=list[FolderResponse])
async def get_folders(parent_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Получить список папок."""
    return list_folders(db, parent_id=parent_id)


@router.post("/folders", response_model=FolderResponse, status_code=201)
async def create_folder_endpoint(
    name: str,
    parent_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Создать папку."""
    return create_folder(db, name=name, parent_id=parent_id)