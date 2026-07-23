"""API v1: подключение всех роутеров."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, documents, chat, artifacts
from app.api.v1.endpoints.artifact_projects import router as artifact_projects_router
from app.api.v1.endpoints.artifact_templates import router as artifact_templates_router
from app.api.v1.endpoints.artifact_themes import router as artifact_themes_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(artifacts.router)
api_router.include_router(artifact_projects_router)
api_router.include_router(artifact_templates_router)
api_router.include_router(artifact_themes_router)