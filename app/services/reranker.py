"""Reranking через Cross-Encoder для точного отбора top-k контекстов."""

from typing import Optional


class Reranker:
    """Переранжирование результатов поиска с помощью Cross-Encoder."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        """Ленивая загрузка Cross-Encoder модели."""
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name)
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
        """Переранжировать документы по релевантности запросу.

        Args:
            query: Текст запроса.
            documents: Список документов с полем 'content'.
            top_k: Сколько результатов вернуть (по умолчанию все).

        Returns:
            Отсортированный список документов с добавленным полем 'rerank_score'.
        """
        self._load_model()

        if not documents:
            return []

        # Подготавливаем пары (query, document)
        pairs = [(query, doc["content"]) for doc in documents]

        # Получаем оценки от Cross-Encoder
        scores = self._model.predict(pairs)

        # Добавляем оценки к документам
        for i, doc in enumerate(documents):
            doc["rerank_score"] = float(scores[i])

        # Сортируем по убыванию оценки
        reranked = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)

        if top_k is not None:
            reranked = reranked[:top_k]

        return reranked