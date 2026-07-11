from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

class Embedding:
    # Локальная модель (загружается один раз для всех экземпляров)
    _model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Клиент Qdrant с постоянным хранилищем (создаётся при первом обращении)
    _client = None

    @classmethod
    def get_qdrant_client(cls, path="./qdrant_storage"):
        """Возвращает постоянного клиента Qdrant (инициализируется один раз)."""
        if cls._client is None:
            cls._client = QdrantClient(path=path)
        return cls._client

    def __init__(self, text: str):
        self.text = text
        self.vector = None

    def make_embedding(self) -> list[float]:
        """Генерирует 384-мерный вектор локально."""
        self.vector = self._model.encode(self.text).tolist()
        return self.vector


     
    def save_to_qdrant(self, collection_name="my_docs", hnsw_params=None):
        """Сохраняет вектор в постоянную коллекцию Qdrant."""
        client = self.get_qdrant_client()
        if not client.collection_exists(collection_name):
            # Базовые параметры HNSW
            default_hnsw = models.HnswConfigDiff(m=16, ef_construct=100)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
                hnsw_config=hnsw_params if hnsw_params else default_hnsw
        )

        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=hash(self.text),  # для примера; лучше UUID
                    vector=self.vector,
                    payload={"text": self.text}
                )
            ]
        )

# Использование
emb = Embedding("Пример текста")
vec = emb.make_embedding()
print(f"Размерность вектора: {len(vec)}")  # 384

# Сохраняем в постоянную базу
emb.save_to_qdrant()

# Данные останутся на диске после выключения компьютера