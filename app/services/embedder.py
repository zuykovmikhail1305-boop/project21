"""Сервис генерации эмбеддингов через sentence-transformers."""

from typing import Optional

import numpy as np


class EmbedderService:
    """Генерация эмбеддингов для текстов."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.device = device
        self._model = None

    def _load_model(self):
        """Ленивая загрузка модели."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                )
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required. Install: pip install sentence-transformers"
                )

    def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг для одного текста."""
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Получить эмбеддинги для списка текстов."""
        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [emb.tolist() for emb in embeddings]

    @property
    def vector_size(self) -> int:
        """Размерность эмбеддинга."""
        self._load_model()
        return self._model.get_embedding_dimension()