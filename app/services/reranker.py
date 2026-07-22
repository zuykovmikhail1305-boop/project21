"""Reranking через Cross-Encoder для точного отбора top-k контекстов."""

import asyncio
from typing import Optional, Any

from app.core import config


class Reranker:
    """Переранжирование результатов поиска с помощью Cross-Encoder.

    Cross-Encoder модель загружается один раз на уровне класса (синглтон),
    чтобы избежать повторной загрузки при каждом вызове rerank().
    """

    _shared_model: Any = None
    _shared_model_name: str = ""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or config.RERANKER_MODEL

    def _load_model(self):
        """Ленивая загрузка Cross-Encoder модели (синглтон на уровне класса).

        Модель загружается один раз и переиспользуется всеми экземплярами Reranker.
        Если model_name отличается от загруженной — загружается новая модель.
        """
        if Reranker._shared_model is not None and Reranker._shared_model_name == self.model_name:
            return

        import logging
        logger = logging.getLogger(__name__)
        try:
            from sentence_transformers import CrossEncoder
            logger.info("[TIMING] Loading cross-encoder model '%s' ...", self.model_name)
            import time
            t0 = time.time()
            Reranker._shared_model = CrossEncoder(self.model_name)
            Reranker._shared_model_name = self.model_name
            logger.info("[TIMING] Cross-encoder model '%s' loaded in %.2fs", self.model_name, time.time() - t0)
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for reranking. "
                "Install: pip install sentence-transformers"
            )

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """Переранжировать документы по релевантности запросу (синхронно).

        Args:
            query: Текст запроса.
            documents: Список документов с полем 'content'.
            top_k: Сколько результатов вернуть (по умолчанию все).

        Returns:
            Отсортированный список документов с добавленным полем 'rerank_score'.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        self._load_model()

        if not documents:
            return []

        # Подготавливаем пары (query, document)
        pairs = [(query, doc["content"]) for doc in documents]

        # Получаем оценки от Cross-Encoder
        scores = Reranker._shared_model.predict(pairs)

        # Добавляем оценки к документам
        for i, doc in enumerate(documents):
            doc["rerank_score"] = float(scores[i])

        # Сортируем по убыванию оценки
        reranked = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)

        if top_k is not None:
            reranked = reranked[:top_k]

        logger.info("[TIMING] rerank() took %.2fs (n_docs=%d, top_k=%s)", time.time() - t0, len(documents), top_k)
        return reranked

    async def rerank_async(
        self,
        query: str,
        documents: list[dict],
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """Переранжировать документы асинхронно (не блокирует event loop).

        Запускает синхронный rerank() в отдельном потоке через run_in_executor.
        """
        import logging
        logger = logging.getLogger(__name__)
        import time
        t0 = time.time()

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.rerank, query, documents, top_k)
        logger.info("[TIMING] rerank_async() took %.2fs (n_docs=%d, top_k=%s)", time.time() - t0, len(documents), top_k)
        return result