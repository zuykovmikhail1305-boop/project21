"""API эндпоинты для пользователей."""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_current_user():
    """Получить текущего пользователя (заглушка)."""
    return {"message": "Current user endpoint - to be implemented"}


@router.get("/")
async def list_users():
    """Список пользователей (заглушка)."""
    return {"message": "Users list endpoint - to be implemented"}