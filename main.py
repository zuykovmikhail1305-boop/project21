import app.routes
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.core.config import Base, SessionLocal, _build_engine
from app.models import *  # noqa: F401, F403 — регистрация всех моделей в Base.metadata
from app.core.seed import seed_groups
from app.api.v1.api import api_router
from app.routes import router as page_router, get_templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI."""
    engine, local_session = _build_engine()

    if engine is not None and local_session is not None:
        try:
            Base.metadata.create_all(bind=engine)
        except Exception:
            pass

        db = local_session()
        try:
            seed_groups(db)
        except Exception:
            pass
        finally:
            db.close()

    yield

    if engine is not None:
        try:
            Base.metadata.drop_all(bind=engine)
        except Exception:
            pass


fastapi_app = FastAPI(title="CorpAI Intelligence", version="0.1.0", lifespan=lifespan)

# === CORS ===
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",  # для React фронтенда в будущем
    ],
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


# === Static files ===
static_dir = Path(__file__).parent / "app/static"
static_dir.mkdir(exist_ok=True)
fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# === Templates ===
templates_dir = Path(__file__).parent / "app/templates"
templates = Jinja2Templates(directory=str(templates_dir))
# Share templates instance with routes module
app.routes.templates = templates

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
