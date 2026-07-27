import requests
import uuid
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv
load_dotenv()


class Embedding:
    def __init__(self):
        # Чтение переменных окружения с дефолтными значениями
        self.emb_model = os.getenv("EMB_MODEL", "all-MiniLM-L6-v2")
        self.qdrant_url = os.getenv("QDRANT_BASE", "http://localhost:6333")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "my_docs")
        self.vector_size = int(os.getenv("VECTOR_SIZE", "384"))  # если есть в .env, иначе 384

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

    def clear_points(self, collection_name=None, batch_size=64):
        if collection_name is None:
            collection_name = self.collection_name

        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.get(collection_url)
        if resp.status_code == 404:
            print(f"⚠️ Коллекция '{collection_name}' не существует. Ничего не удаляем.")
            return
        elif resp.status_code != 200:
            raise Exception(f"Не удалось получить информацию о коллекции: {resp.text}")

        scroll_url = f"{collection_url}/points/scroll"
        scroll_payload = {"limit": batch_size, "with_payload": False}
        points_deleted = 0
        while True:
            resp = requests.post(scroll_url, json=scroll_payload)
            if resp.status_code != 200:
                raise Exception(f"Ошибка при получении точек: {resp.text}")
            data = resp.json()
            result = data.get("result", {})
            points = result.get("points", [])
            if not points:
                break
            point_ids = [p["id"] for p in points]
            delete_payload = {"points": point_ids}
            delete_resp = requests.post(f"{collection_url}/points/delete", json=delete_payload)
            if delete_resp.status_code != 200:
                raise Exception(f"Ошибка при удалении точек: {delete_resp.text}")
            points_deleted += len(point_ids)
            scroll_payload["offset"] = result.get("next_page_offset")
            if not scroll_payload["offset"]:
                break
            print(f"Удалено {points_deleted} точек...")
        print(f"✅ Все точки удалены. Всего удалено: {points_deleted}")
