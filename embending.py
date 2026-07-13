from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
import uuid


class Embedding:

    _client = None

    @classmethod
    def get_client(cls, path="./qdrant_storage"):
        if cls._client is None:
            cls._client = QdrantClient(path=path)
        return cls._client

    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

    def encode(self, text):
        return self.model.encode(text).tolist()

    def _extract_text_and_metadata(self, item):
        """
        Извлекает текст и метаданные из элемента,
        который может быть словарём или объектом Node (LlamaIndex).
        """
        if isinstance(item, dict):
            return item.get('text', ''), item.get('metadata', {})
        else:
            # Предполагаем, что это объект с атрибутами text и metadata
            text = getattr(item, 'text', '')
            metadata = getattr(item, 'metadata', {})
            return text, metadata

    def save_to_qdrant(self, data, collection_name="my_docs", batch_size=64):
        # 1. Преобразуем data в единый формат — список словарей с ключами 'text', 'metadata', 'vector'
        processed_data = []
        for item in data:
            text, metadata = self._extract_text_and_metadata(item)
            vector = self.encode(text)
            processed_data.append({
                'text': text,
                'metadata': metadata,
                'vector': vector
            })

        client = self.get_client()

        # 2. Создаём коллекцию, если её нет
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=self.model.get_sentence_embedding_dimension(),
                    distance=models.Distance.COSINE
                )
            )

        # 3. Формируем точки для загрузки
        points = []
        for item in processed_data:
            point_id = str(uuid.uuid4())
            payload = {
                "text": item['text'],
                "metadata": item['metadata']
            }
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=item['vector'],
                    payload=payload
                )
            )

        # 4. Загружаем пакетами
        total = len(points)
        for i in range(0, total, batch_size):
            batch = points[i:i+batch_size]
            client.upsert(collection_name=collection_name, points=batch)
        print(f"Сохранено {total} точек в коллекцию '{collection_name}'")


    def search(self, query, collection_name="my_docs", limit=20):
        client = self.get_client()
        query_vector = self.encode(query)
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            with_payload=True
        )
        return [{"score": hit.score, "payload": hit.payload} for hit in results]
