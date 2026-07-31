"""Асинхронный эмбеддер.

Использует SentenceTransformer в thread pool (CPU-bound).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from sentence_transformers import SentenceTransformer

from app.core.config import EMBEDDING_MODEL, EMBEDDING_DEVICE

logger = logging.getLogger(__name__)


class AsyncEmbedder:
    """Асинхронный эмбеддер.

    SentenceTransformer.encode() — CPU-bound операция,
    выполняется в thread pool для незаблокировки event loop.
    """

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        device: str = EMBEDDING_DEVICE,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        """Load model synchronously (called in thread pool)."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name} on {self.device}")
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    async def embed(self, text: str) -> list[float]:
        """Embed a single text asynchronously."""
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, self._load_model)
        vector = await loop.run_in_executor(
            None, model.encode, text
        )
        return vector.tolist()

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts asynchronously.

        Использует batch-encode SentenceTransformer для эффективности.
        """
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, self._load_model)
        vectors = await loop.run_in_executor(
            None, lambda: model.encode(texts, show_progress_bar=False)
        )
        return [v.tolist() for v in vectors]

    @property
    def vector_size(self) -> int:
        """Get the embedding vector size."""
        model = self._load_model()
        return model.get_sentence_embedding_dimension()
