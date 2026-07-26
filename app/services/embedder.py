"""Embedder Service - совместимая версия для старого кода (обёртка над rag_embedder.py)."""

from app.services.rag_embedder import Embedding
import os
from dotenv import load_dotenv

load_dotenv()


class EmbedderService:
    """Embedding service - обёртка для обратной совместимости."""

    def __init__(self, model_name=None, device=None):
        self.model_name = model_name or os.getenv("EMB_MODEL", "all-MiniLM-L6-v2")
        self.device = device or os.getenv("EMBEDDING_DEVICE", "cpu")
        self._embedding = Embedding()
        self.model = self._embedding.model

    def _load_model(self):
        """Загрузить модель (для совместимости)."""
        pass

    def embed(self, text: str):
        """Создать эмбеддинг для текста."""
        return self._embedding.encode_dense(text)

    def embed_batch(self, texts: list):
        """Создать эмбеддинги для списка текстов."""
        return [self.embed(text) for text in texts]
