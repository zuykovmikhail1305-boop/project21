import requests
import uuid
from sentence_transformers import SentenceTransformer

class Embedding:
    def __init__(self, qdrant_url="http://localhost:6333"):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.qdrant_url = qdrant_url

    def encode(self, text):
        return self.model.encode(text).tolist()

    def _extract_text_and_metadata(self, item):
        if isinstance(item, dict):
            return item.get('text', ''), item.get('metadata', {})
        else:
            text = getattr(item, 'text', '')
            metadata = getattr(item, 'metadata', {})
            return text, metadata

    def save_to_qdrant(self, data, collection_name="my_docs", batch_size=64):
        # Генерируем векторы и формируем точки
        points = []
        for item in data:
            text, metadata = self._extract_text_and_metadata(item)
            vector = self.encode(text)
            point_id = str(uuid.uuid4())
            points.append({
                "id": point_id,
                "vector": vector,
                "payload": {"text": text, "metadata": metadata}
            })

        # Проверяем/создаём коллекцию
        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.get(collection_url)
        if resp.status_code == 404:
            create_payload = {
                "vectors": {
                    "size": 384,
                    "distance": "Cosine"
                }
            }
            resp = requests.put(collection_url, json=create_payload)
            if resp.status_code != 200:
                raise Exception(f"Failed to create collection: {resp.text}")
        elif resp.status_code != 200:
            raise Exception(f"Unexpected response: {resp.text}")

        # Загружаем точки пакетами
        total = len(points)
        for i in range(0, total, batch_size):
            batch = points[i:i+batch_size]
            resp = requests.put(
                f"{collection_url}/points",
                json={"points": batch}
            )
            if resp.status_code != 200:
                raise Exception(f"Failed to upsert points: {resp.text}")
            print(f"Сохранено {min(i+batch_size, total)} из {total}")
        print(f"✅ Все {total} точек сохранены в коллекцию '{collection_name}'")

    def search_query(self, query, collection_name="my_docs", limit=1, return_text_only=False):
        query_vector = self.encode(query)
        search_payload = {
            "vector": query_vector,
            "limit": limit,
            "with_payload": True
        }
        resp = requests.post(
            f"{self.qdrant_url}/collections/{collection_name}/points/search",
            json=search_payload
        )
        if resp.status_code != 200:
            raise Exception(f"Search failed: {resp.text}")
        data = resp.json()
        results = data.get("result", [])
        if return_text_only:
            return [hit["payload"]["text"] for hit in results]
        else:
            return [{"score": hit["score"], "payload": hit["payload"]} for hit in results]