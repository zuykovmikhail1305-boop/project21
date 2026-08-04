"""RAG Embedder: работа с векторными эмбеддингами и Qdrant."""

import requests
import uuid
from sentence_transformers import SentenceTransformer
from app.core.config import EMB_MODEL, QDRANT_BASE, QDRANT_COLLECTION, VECTOR_SIZE


class Embedding:
    def __init__(self):
        # Чтение переменных окружения с дефолтными значениями
        self.emb_model = EMB_MODEL
        self.qdrant_url = QDRANT_BASE
        self.collection_name = QDRANT_COLLECTION
        self.vector_size = VECTOR_SIZE

        self.model = SentenceTransformer(self.emb_model)

    def encode_dense(self, text):
        return self.model.encode(text).tolist()

    def _extract_text_and_metadata(self, item):
        if isinstance(item, dict):
            return item.get('text', ''), item.get('metadata', {})
        else:
            text = getattr(item, 'text', '')
            metadata = getattr(item, 'metadata', {})
            return text, metadata

    def save_to_qdrant(self, data, collection_name=None, batch_size=64):
        if collection_name is None:
            collection_name = self.collection_name

        points = []
        for item in data:
            text, metadata = self._extract_text_and_metadata(item)
            dense_vec = self.encode_dense(text)
            point_id = str(uuid.uuid4())
            points.append({
                "id": point_id,
                "vector": dense_vec,
                "payload": {"text": text, "metadata": metadata}
            })

        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.get(collection_url)
        if resp.status_code == 404:
            create_payload = {"vectors": {"size": self.vector_size, "distance": "Cosine"}}
            resp = requests.put(collection_url, json=create_payload)
            if resp.status_code != 200:
                raise Exception(f"Failed to create collection: {resp.text}")
        elif resp.status_code != 200:
            raise Exception(f"Unexpected response: {resp.text}")

        total = len(points)
        for i in range(0, total, batch_size):
            batch = points[i:i + batch_size]
            resp = requests.put(f"{collection_url}/points", json={"points": batch})
            if resp.status_code != 200:
                raise Exception(f"Failed to upsert points: {resp.text}")
            print(f"Сохранено {min(i + batch_size, total)} из {total}")
        print(f"✅ Все {total} точек сохранены в коллекцию '{collection_name}'")

    def dense_search(self, query, collection_name=None, limit=20):
        if collection_name is None:
            collection_name = self.collection_name

        dense_vec = self.encode_dense(query)
        search_payload = {
            "vector": dense_vec,
            "limit": limit,
            "with_payload": True
        }
        resp = requests.post(
            f"{self.qdrant_url}/collections/{collection_name}/points/search",
            json=search_payload
        )
        if resp.status_code != 200:
            raise Exception(f"Dense search failed: {resp.text}")
        data = resp.json()
        results = data.get("result", [])
        return [{
            "text": hit["payload"]["text"],
            "metadata": hit["payload"]["metadata"],
            "score": hit["score"],
            "id": hit["id"]
        } for hit in results]

    def delete_collection(self, collection_name=None):
        if collection_name is None:
            collection_name = self.collection_name

        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.delete(collection_url)
        if resp.status_code == 200:
            print(f"✅ Коллекция '{collection_name}' успешно удалена.")
        elif resp.status_code == 404:
            print(f"⚠️ Коллекция '{collection_name}' не найдена, ничего не делаем.")
        else:
            raise Exception(f"Ошибка при удалении коллекции: {resp.text}")
