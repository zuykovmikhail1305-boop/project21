"""Сервис генерации эмбеддингов через sentence-transformers или GigaChat."""

import asyncio
import logging
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
        """Ленивая инициализация провайдера LLM для эмбеддингов.

        GigaChat embeddings требуют оплаты (402 Payment Required).
        По умолчанию используем sentence-transformers (локально).
        """
        return None  # GigaChat embeddings не используются из-за оплаты

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
            import logging
            logger = logging.getLogger(__name__)
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("[TIMING] Loading embedding model '%s' on %s ...", self.model_name, self.device)
                import time
                t0 = time.time()
                self._model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                )
                logger.info("[TIMING] Embedding model '%s' loaded in %.2fs", self.model_name, time.time() - t0)
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required. Install: pip install sentence-transformers"
                ) from exc

    def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг для одного текста (синхронно)."""
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        provider = self._get_provider()
        if provider is not None:
            result = self._embed_with_gigachat(text)
            logger.info("[TIMING] embed() via GigaChat took %.2fs (text_len=%d)", time.time() - t0, len(text))
            return result

        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        logger.info("[TIMING] embed() via sentence-transformers took %.2fs (text_len=%d)", time.time() - t0, len(text))
        return embedding.tolist()

    async def embed_async(self, text: str) -> list[float]:
        """Получить эмбеддинг асинхронно (не блокирует event loop).

        Запускает синхронный embed() в отдельном потоке через run_in_executor,
        чтобы не блокировать event loop FastAPI.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.embed, text)
        logger.info("[TIMING] embed_async() took %.2fs (text_len=%d)", time.time() - t0, len(text))
        return result

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Получить эмбеддинги для списка текстов."""
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        provider = self._get_provider()
        if provider is not None:
            result = [self._embed_with_gigachat(text) for text in texts]
            logger.info("[TIMING] embed_batch() via GigaChat took %.2fs (n=%d)", time.time() - t0, len(texts))
            return result

        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        logger.info("[TIMING] embed_batch() via sentence-transformers took %.2fs (n=%d)", time.time() - t0, len(texts))
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
