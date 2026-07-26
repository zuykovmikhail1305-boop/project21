"""Reranker Service - совместимая версия для старого кода (обёртка над rag_finder.py)."""

from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv

load_dotenv()


class Reranker:
    """Cross-encoder reranker - обёртка для обратной совместимости."""

    def __init__(self, model_name=None):
        self.model_name = model_name or os.getenv("CROSS_ENC", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.model = None

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
