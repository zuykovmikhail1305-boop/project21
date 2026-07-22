"""HTML page routes for the frontend (Jinja2 templates)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.chat import ChatSession, ChatMessage, SessionStatus
from app.models.artifact_v2 import ArtifactProject

router = APIRouter()

# Templates are configured in main.py
templates: Jinja2Templates = None  # Set by main.py


def get_templates() -> Jinja2Templates:
    """Get the Jinja2Templates instance configured in main.py."""
    global templates
    return templates


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index_page(request: Request, db: Session = Depends(get_db)):
    """Main page with search and quick actions."""
    recent_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.status == SessionStatus.ACTIVE)
        .order_by(ChatSession.updated_at.desc())
        .limit(5)
        .all()
    )
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "main.html",
        context={
            "request": request,
            "active_page": "main",
            "recent_sessions": recent_sessions,
        },
    )


@router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request, q: str = ""):
    """Chat interface page. Accepts optional ?q= query to auto-submit."""
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "chat.html",
        context={
            "request": request,
            "active_page": "chat",
            "initial_query": q,
        },
    )


@router.get("/library", response_class=HTMLResponse, include_in_schema=False)
async def library_page(request: Request, db: Session = Depends(get_db)):
    """Library page with document grid."""
    documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .limit(50)
        .all()
    )
    total_count = db.query(func.count(Document.id)).scalar() or 0
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "labrary.html",
        context={
            "request": request,
            "active_page": "library",
            "documents": documents,
            "total_count": total_count,
        },
    )


@router.get("/projects", response_class=HTMLResponse, include_in_schema=False)
async def projects_page(request: Request, db: Session = Depends(get_db)):
    """Projects page with artifact grid."""
    projects = (
        db.query(ArtifactProject)
        .order_by(ArtifactProject.created_at.desc())
        .limit(50)
        .all()
    )
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "projects.html",
        context={
            "request": request,
            "active_page": "projects",
            "projects": projects,
        },
    )


@router.get("/documents", response_class=HTMLResponse, include_in_schema=False)
async def documents_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Documents management page."""
    documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .limit(50)
        .all()
    )
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        name="documents.html",
        request=request,
        context={
            "request": request,
            "active_page": "documents",
            "documents": documents,
        },
    )


@router.get("/documents/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
async def document_view_page(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
):
    """Document view page with AI summary panel."""
    from fastapi.responses import RedirectResponse

    document = db.query(Document).filter(Document.id == doc_id).first()
    if not document:
        return RedirectResponse(url="/documents")

    chunks = document.chunks
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "view_in_the_document.html",
        context={
            "request": request,
            "active_page": "documents",
            "document": document,
            "chunks": chunks,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard with system statistics."""
    # Document stats
    total_documents = db.query(func.count(Document.id)).scalar() or 0
    ready_documents = (
        db.query(func.count(Document.id))
        .filter(Document.status == "ready")
        .scalar() or 0
    )
    processing_documents = (
        db.query(func.count(Document.id))
        .filter(Document.status == "processing")
        .scalar() or 0
    )

    # Chunk stats (approximate from Qdrant — for MVP use DB count)
    total_chunks = (
        db.query(func.count(Document.id))
        .filter(Document.status == "ready")
        .scalar() or 0
    ) * 10  # rough estimate

    # Session stats
    total_sessions = (
        db.query(func.count(ChatSession.id))
        .filter(ChatSession.status == SessionStatus.ACTIVE)
        .scalar() or 0
    )

    # Storage used
    storage_result = db.query(func.sum(Document.file_size)).scalar() or 0
    storage_mb = storage_result / (1024 * 1024)
    storage_used = f"{storage_mb:.1f} MB"

    # Recent documents
    recent_documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .limit(5)
        .all()
    )

    # Recent messages
    recent_messages = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
        .all()
    )

    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard",
            "stats": {
                "total_documents": total_documents,
                "ready_documents": ready_documents,
                "processing_documents": processing_documents,
                "total_chunks": total_chunks,
                "total_sessions": total_sessions,
                "storage_used": storage_used,
            },
            "recent_documents": recent_documents,
            "recent_messages": recent_messages,
        },
    )


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(request: Request):
    """Settings page."""
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
        },
    )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    """Login page."""
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request, "login.html",
        {
            "request": request,
            "active_page": "login",
        },
    )


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    """Register page."""
    tmpl = get_templates()
    return tmpl.TemplateResponse(
        request, "register.html",
        {
            "request": request,
            "active_page": "register",
        },
    )