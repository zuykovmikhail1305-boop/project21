"""Сервис генерации эмбеддингов через sentence-transformers или GigaChat."""

import asyncio
from typing import Optional

from app.core import config


class EmbedderService:
    """Генерация эмбеддингов для текстов."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        provider: Optional[object] = None,
    ):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._provider = provider

    def _get_provider(self):
        """Ленивая инициализация провайдера LLM для эмбеддингов."""
        has_gigachat_creds = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )
        if (
            self._provider is None
            and getattr(config, "LLM_PROVIDER", "openai") == "gigachat"
            and has_gigachat_creds
        ):
            from app.services.gigachat_provider import GigaChatClient
            self._provider = GigaChatClient()
        return self._provider

    def _embed_with_gigachat(self, text: str) -> list[float]:
        """Получить эмбеддинг через GigaChat."""
        provider = self._get_provider()
        if provider is None:
            raise RuntimeError("GigaChat provider is not configured")

        try:
            return asyncio.run(provider.generate_embeddings(text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(provider.generate_embeddings(text))
            finally:
                loop.close()

    def _load_model(self):
        """Ленивая загрузка локальной модели."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                )
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required. Install: pip install sentence-transformers"
                ) from exc

    def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг для одного текста."""
        provider = self._get_provider()
        if provider is not None:
            return self._embed_with_gigachat(text)

        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Получить эмбеддинги для списка текстов."""
        provider = self._get_provider()
        if provider is not None:
            return [self._embed_with_gigachat(text) for text in texts]

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
        provider = self._get_provider()
        if provider is not None:
            sample = self.embed("sample")
            return len(sample)

        self._load_model()
        return self._model.get_embedding_dimension()
