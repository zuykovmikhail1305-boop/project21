"""API v1: подключение всех роутеров."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, documents, chat, artifacts

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(artifacts.router)