"""DI-зависимости для FastAPI: Qdrant, S3, LLM клиенты."""

from functools import lru_cache
from qdrant_client import QdrantClient
from app.core import config


@lru_cache
def get_qdrant_client() -> QdrantClient:
    """Get or create Qdrant client singleton."""
    return QdrantClient(
        host=config.QDRANT_HOST,
        port=config.QDRANT_PORT,
    )


def get_storage_provider():
    """Get storage provider (mock S3 / local filesystem for MVP)."""
    from app.services.storage import MockStorageProvider
    return MockStorageProvider(storage_path=config.LOCAL_STORAGE_PATH)


def get_llm_provider():
    """Get LLM provider based on config."""
    if config.LLM_PROVIDER == "gigachat":
        from app.services.gigachat_provider import GigaChatClient
        return GigaChatClient()
    else:
        from app.services.llm_provider import OpenAIClient
        return OpenAIClient(
            api_key=config.OPENAI_API_KEY,
            api_base=config.OPENAI_API_BASE,
            model=config.OPENAI_MODEL,
        )


def get_embedder():
    """Get embedding service."""
    from app.services.embedder import EmbedderService
    return EmbedderService(
        model_name=config.EMBEDDING_MODEL,
        device=config.EMBEDDING_DEVICE,
    )