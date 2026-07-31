"""Embedder Service - совместимая версия для старого кода (обёртка над rag_embedder.py)."""

from app.services.rag_embedder import Embedding
import os
from dotenv import load_dotenv

from app.core import config
import os
from dotenv import load_dotenv
load_dotenv()

class EmbedderService:
    """Embedding service - обёртка для обратной совместимости."""

    def __init__(
        self,
        model_name: str = str(os.getenv('EMB_MODEL')),
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
        """Загрузить модель (для совместимости)."""
        pass

    def embed(self, text: str):
        """Создать эмбеддинг для текста."""
        return self._embedding.encode_dense(text)

    def embed_batch(self, texts: list):
        """Создать эмбеддинги для списка текстов."""
        return [self.embed(text) for text in texts]
