"""GigaChat RAG Service - совместимая версия для старого кода (обёртка над новыми RAG сервисами)."""

import logging
from typing import Optional, List, Dict, Any

from app.services.vector_store import VectorStore
from app.services.reranker import Reranker
from app.services.embedder import EmbedderService
from app.services.rag_embedder import Embedding
from app.services.document_processor import Processing
from app.services.bm25_searcher import BM25Search
import os
import pickle
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class GigaChatRAGService:
    """GigaChat RAG Service - обёртка для совместимости со старым кодом."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbedderService] = None,
        reranker: Optional[Reranker] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedder = embedder or EmbedderService()
        self.reranker = reranker or Reranker()
        self.embedding = Embedding()
        self.logger = logger

    async def search(
        self,
        query: str,
        user_groups: List[int],
        history: Optional[List[Dict]] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """Поиск релевантных документов (для совместимости)."""
        # Используем векторный поиск
        results = self.vector_store.search(query, limit=limit)

        # Переранжируем результаты если есть
        if results:
            results = self.reranker.rerank(query, results, top_k=min(5, len(results)))

        return results

    def index_document(
        self,
        file_path: str,
        document_id: int,
    ) -> List[Dict]:
        """Индексировать документ (парсинг + чанкинг + эмбеддинги)."""
        try:
            # Парсируем документ
            processor = Processing(file_path)
            chunks = processor.chunking()

            if not chunks:
                self.logger.warning(f"No chunks extracted from {file_path}")
                return []

            # Преобразуем chunks в нужный формат
            points = []
            for chunk in chunks:
                point = {
                    "text": chunk.text,
                    "metadata": {
                        "document_id": document_id,
                        "page_number": chunk.metadata.get("page_number"),
                        "filename": chunk.metadata.get("filename", os.path.basename(file_path)),
                    }
                }
                points.append(point)

            # Сохраняем в Qdrant
            self.embedding.save_to_qdrant(points)

            return points

        except Exception as e:
            self.logger.error(f"Error indexing document {file_path}: {e}")
            raise
