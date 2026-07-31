"""RAG Indexer: индексация документов в Qdrant и BM25."""

import os
import pickle

from dotenv import load_dotenv
from embending import Embedding
from processing import Processing

load_dotenv()

class CreateIndex:
    def __init__(self):
        self.emb = Embedding()
        self.collection_name=os.getenv("QDRANT_COLLECTION"),
        self.recreate=False,
        self.chunking_threshold=os.getenv("CHUNK_THRESHOLD", 75)

    def create_index(self, file_path=None, id=None):
        """
        Создаёт Qdrant-коллекцию и BM25 индекс для документа.

        :param file_path: путь к документу
        :param collection_name: имя коллекции в Qdrant
        :param index_file: файл для сохранения BM25 индекса
        :param recreate: если True, удаляет существующую коллекцию и индекс перед созданием
        :param chunking_threshold: зарезервирован для будущей настройки чанкинга
        """
        if not file_path:
            raise ValueError("file_path не задан")

        emb = Embedding()

        if self.recreate:
            emb.delete_collection(self.collection_name)
        try:
            processor = Processing()
            chunks = processor.chunking(file_path, doc_id=id)
        except Exception as exc:
            raise RuntimeError(f"Ошибка при обработке {file_path}: {exc}") from exc

        if not chunks:
            return None

        emb.save_to_qdrant(
            chunks,
            collection_name=self.collection_name,
            batch_size=64,
        )

