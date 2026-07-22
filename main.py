import app.routes
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.core.config import Base, SessionLocal, _build_engine, CORS_ORIGINS
from app.models import *  # noqa: F401, F403 — регистрация всех моделей в Base.metadata
from app.core.seed import seed_groups
from app.api.v1.api import api_router
from app.routes import router as page_router, get_templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI."""
    # Настройка логирования: все логи уровня INFO и выше пишутся в stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging configured: level=INFO")

    # Предзагрузка моделей ML при старте (чтобы не блокировать event loop при первом запросе)
    try:
        logger.info("Preloading embedding model...")
        from app.services.embedder import EmbedderService
        embedder = EmbedderService()
        embedder._load_model()
        logger.info("Embedding model preloaded successfully")
    except Exception as e:
        logger.warning("Failed to preload embedding model: %s", e)

    try:
        logger.info("Preloading cross-encoder model...")
        from app.core import config as app_config
        from app.services.reranker import Reranker
        reranker = Reranker(model_name=app_config.RERANKER_MODEL)
        reranker._load_model()
        logger.info("Cross-encoder model '%s' preloaded successfully", app_config.RERANKER_MODEL)
    except Exception as e:
        logger.warning("Failed to preload cross-encoder model: %s", e)

    # --- Database initialization with retry ---
    import time
    from sqlalchemy import text

    engine = None
    local_session = None

    max_retries = 5
    retry_delay = 3  # seconds

    for attempt in range(1, max_retries + 1):
        try:
            engine, local_session = _build_engine()
            if engine is None or local_session is None:
                raise RuntimeError("_build_engine() returned None")

            # Проверяем соединение с БД
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection established (attempt %d/%d)", attempt, max_retries)
            break
        except Exception as e:
            logger.warning(
                "Database connection failed (attempt %d/%d): %s",
                attempt, max_retries, e,
            )
            engine = None
            local_session = None
            if attempt < max_retries:
                logger.info("Retrying in %d seconds...", retry_delay)
                time.sleep(retry_delay)

    if engine is not None and local_session is not None:
        # --- Create all tables ---
        try:
            logger.info("Creating database tables via Base.metadata.create_all...")
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created/verified successfully")
        except Exception as e:
            logger.error("Failed to create database tables: %s", e)
            logger.error(
                "Ensure the database 'project21' exists. "
                "On VPS, run: docker compose exec postgres createdb -U postgres project21"
            )

        # --- Seed default data ---
        db = local_session()
        try:
            seed_groups(db)
            logger.info("Seed data applied successfully")
        except Exception as e:
            logger.warning("Failed to apply seed data: %s", e)
        finally:
            db.close()
    else:
        logger.error(
            "Database is not available after %d retries. "
            "The application will start but database-dependent features will fail.",
            max_retries,
        )

    yield

    if engine is not None:
        try:
            logger.info("Dropping all tables on shutdown...")
            Base.metadata.drop_all(bind=engine)
            logger.info("All tables dropped")
        except Exception as e:
            logger.warning("Failed to drop tables on shutdown: %s", e)


fastapi_app = FastAPI(title="CorpAI Intelligence", version="0.1.0", lifespan=lifespan)

# === CORS ===
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Security Headers Middleware ===


@fastapi_app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store"
    return response


# === 401 Unauthorized Exception Handler ===


@fastapi_app.exception_handler(HTTPException)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Перехватывает HTTPException со статусом 401 и отображает страницу 401.html."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        templates = get_templates()
        return templates.TemplateResponse(
            request,
            "401.html",
            {
                "request": request,
                "active_page": "401",
                "detail": exc.detail if exc.detail else "",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    # Для остальных HTTPException — стандартное поведение
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# === Static files ===
static_dir = Path(__file__).parent / "app/static"
static_dir.mkdir(exist_ok=True)
fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# === Templates ===
templates_dir = Path(__file__).parent / "app/templates"
templates = Jinja2Templates(directory=str(templates_dir))
# Share templates instance with routes module
app.routes.templates = templates

# === Healthcheck (before all routers, guaranteed available) ===
@fastapi_app.get("/health")
async def health():
    return {"status": "ok"}


# === API Routes ===
fastapi_app.include_router(api_router)

# === Page Routes (HTML) ===
fastapi_app.include_router(page_router)


@fastapi_app.get("/")
async def root():
    return {"message": "CorpAI Intelligence API", "status": "running"}


if __name__ == "__main__":  # for local development only, use uvicorn command for production
    import uvicorn
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)
