"""RAG Indexer: индексация документов в Qdrant и BM25."""

import pickle

from app.RAG_Misha.embending import Embedding
from app.RAG_Misha.processing import Processing
from app.core.config import QDRANT_COLLECTION, CHUNK_THRESHOLD

class CreateIndex:
    def __init__(self):
        self.emb = Embedding()
        self.collection_name = QDRANT_COLLECTION
        self.recreate = False
        self.chunking_threshold = int(CHUNK_THRESHOLD)

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
            emb.delete_collection(collection_name=self.collection_name)
        try:
            processor = Processing()
            chunks = processor.chunking(original_path=file_path, doc_id=id)
        except Exception as exc:
            raise RuntimeError(f"Ошибка при обработке {file_path}: {exc}") from exc

        if not chunks:
            return None

        emb.save_to_qdrant(
            chunks,
            collection_name=self.collection_name,
            batch_size=64,
        )
