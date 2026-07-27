"""Vector Store - совместимая версия для старого кода (обёртка над rag_embedder.py)."""

from app.services.rag_embedder import Embedding
import os
from dotenv import load_dotenv

load_dotenv()


class VectorStore:
    """Vector store for Qdrant - обёртка для обратной совместимости."""

    def __init__(self):
        self.embedding = Embedding()
        self.qdrant_url = os.getenv("QDRANT_BASE", "http://localhost:6333")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "my_docs")

    def search(self, query: str, limit: int = 20, collection_name: str = None):
        """Поиск в векторном хранилище."""
        if collection_name is None:
            collection_name = self.collection_name

        results = self.embedding.dense_search(query, collection_name=collection_name, limit=limit)
        return results

    def save_vectors(self, data, collection_name: str = None):
        """Сохранить векторы в Qdrant."""
        if collection_name is None:
            collection_name = self.collection_name

        self.embedding.save_to_qdrant(data, collection_name=collection_name)
