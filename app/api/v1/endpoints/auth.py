"""API эндпоинты для аутентификации."""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login():
    """Вход в систему (заглушка)."""
    return {"message": "Login endpoint - to be implemented"}


@router.post("/register")
async def register():
    """Регистрация (заглушка)."""
    return {"message": "Register endpoint - to be implemented"}