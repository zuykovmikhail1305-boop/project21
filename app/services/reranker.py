"""Reranker Service - совместимая версия для старого кода (обёртка над rag_finder.py)."""

from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv

load_dotenv()

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
        """Загрузить модель."""
        if self.model is None:
            self.model = CrossEncoder(self.model_name)

    def rerank(self, query: str, candidates: list, top_k: int = 5) -> list:
        """Переранжировать кандидатов по релевантности."""
        if self.model is None:
            self._load_model()

        if not candidates:
            return []

        pairs = [
            (query,
             cand.get(
                 'text',
                 str(cand))) if isinstance(
                cand,
                dict) else (
                query,
                cand) for cand in candidates]
        scores = self.model.predict(pairs)

        for cand, score in zip(candidates, scores):
            if isinstance(cand, dict):
                cand['rerank_score'] = float(score)

        ranked = sorted(candidates, key=lambda x: x.get('rerank_score', 0) if isinstance(x, dict) else 0, reverse=True)
        return ranked[:top_k]
