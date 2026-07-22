"""API эндпоинты для аутентификации: register, login, logout, refresh, me."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_db, ACCESS_TOKEN_EXPIRE_MINUTES
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, LoginRequest, UserResponse, TokenResponse
from app.services.user import UserService
from app.services.token import TokenService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
)
async def register(
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    """Зарегистрировать нового пользователя.

    - Создаёт пользователя с указанным email, username и password
    - Хеширует пароль через bcrypt
    - Добавляет пользователя в группу "users" по умолчанию
    - Не требует подтверждения email (MVP)

    Args:
        user_in: Данные для регистрации (email, username, password).

    Returns:
        UserResponse с id, email, username, is_active, created_at.

    Raises:
        HTTPException 400: Если email уже занят или пароль не проходит валидацию.
    """
    user_service = UserService(db)

    try:
        user = await user_service.register(
            email=user_in.email,
            username=user_in.username,
            password=user_in.password,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return UserResponse(
        id=user.id,  # type: ignore[arg-type]
        email=str(user.email),
        username=str(user.username),
        is_active=bool(user.is_active),
        created_at=user.created_at,  # type: ignore[arg-type]
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход в систему",
)
async def login(
    user_in: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Аутентификация пользователя и получение JWT токенов.

    - Проверяет email и пароль
    - Возвращает access_token (30 мин) и refresh_token (7 дней)
    - Устанавливает httpOnly cookie с access_token для HTML-страниц
    - Refresh token сохраняется в БД для возможности отзыва

    Args:
        user_in: Данные для входа (email, password).
        request: HTTP запрос.
        response: HTTP ответ (для установки cookie).

    Returns:
        TokenResponse с access_token, refresh_token, token_type.

    Raises:
        HTTPException 401: Если email или пароль неверны.
    """
    user_service = UserService(db)
    token_service = TokenService(db)

    user = await user_service.authenticate(
        email=user_in.email,
        password=user_in.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    tokens = await token_service.create_tokens(user_id=user.id)  # type: ignore[arg-type]

    # Устанавливаем httpOnly cookie с access_token для HTML-страниц
    # Cookie не httpOnly, чтобы JS тоже мог его читать (для refresh)
    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        secure=False,  # True в production с HTTPS
        httponly=False,  # False чтобы JS мог читать (для base.html)
        samesite="lax",
    )

    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access token",
)
async def refresh(
    refresh_token_body: dict,
    db: Session = Depends(get_db),
):
    """Обновить пару токенов по refresh token (token rotation).

    - Старый refresh token помечается как revoked
    - Выдаётся новая пара access + refresh токенов

    Args:
        refresh_token_body: {"refresh_token": "..."}.

    Returns:
        TokenResponse с новыми access_token, refresh_token, token_type.

    Raises:
        HTTPException 401: Если refresh token невалиден, истёк или отозван.
    """
    refresh_token_str = refresh_token_body.get("refresh_token")
    if not refresh_token_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh_token is required",
        )

    token_service = TokenService(db)
    tokens = await token_service.refresh_tokens(refresh_token_str)

    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked refresh token",
        )

    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
    )


@router.post(
    "/logout",
    summary="Выход из системы",
)
async def logout(
    refresh_token_body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отозвать refresh token (выход из системы).

    - Помечает refresh token как revoked
    - Access token продолжает жить до истечения срока

    Args:
        refresh_token_body: {"refresh_token": "..."}.

    Returns:
        {"message": "Logged out successfully"}.

    Raises:
        HTTPException 400: Если refresh_token не указан.
        HTTPException 401: Если access token невалиден (через Depends).
    """
    refresh_token_str = refresh_token_body.get("refresh_token")
    if not refresh_token_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh_token is required",
        )

    token_service = TokenService(db)
    success = await token_service.revoke_refresh_token(refresh_token_str)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh token not found",
        )

    return {"message": "Logged out successfully"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Информация о текущем пользователе",
)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """Получить информацию о текущем аутентифицированном пользователе.

    Args:
        current_user: Текущий пользователь (из JWT access token).

    Returns:
        UserResponse с id, email, username, is_active, created_at.
    """
    return UserResponse(
        id=current_user.id,  # type: ignore[arg-type]
        email=str(current_user.email),
        username=str(current_user.username),
        is_active=bool(current_user.is_active),
        created_at=current_user.created_at,  # type: ignore[arg-type]
    )