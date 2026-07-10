from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager


from app.core.config import engine, Base
from app.models import *  # noqa: F401, F403 — регистрация всех моделей в Base.metadata
from app.api.v1.api import api_router
from app.routes import router as page_router, get_templates

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI."""
    # Startup
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown
    Base.metadata.drop_all(bind=engine)

fastapi_app = FastAPI(title="CorpAI Intelligence", version="0.1.0", lifespan=lifespan)

# === Static files ===
static_dir = Path(__file__).parent / "app/static"
static_dir.mkdir(exist_ok=True)
fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# === Templates ===
templates_dir = Path(__file__).parent / "app/templates"
templates = Jinja2Templates(directory=str(templates_dir))
# Share templates instance with routes module
import app.routes
app.routes.templates = templates

# === API Routes ===
fastapi_app.include_router(api_router)

# === Page Routes (HTML) ===
fastapi_app.include_router(page_router)

# @
# async def on_startup():
#     """Create database tables on startup (for MVP)."""
#     Base.metadata.create_all(bind=engine)


@fastapi_app.get("/")
async def root():
    return {"message": "CorpAI Intelligence API", "status": "running"}


if __name__ == "__main__": # for local development only, use uvicorn command for production
    import uvicorn
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)
