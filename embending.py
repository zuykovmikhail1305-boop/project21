import requests
import uuid
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer

class Embedding:
    def __init__(self, qdrant_url="http://localhost:6333"):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.qdrant_url = qdrant_url
        # Инициализируем TF-IDF векторизатор (можно добавить стоп-слова для русского)
        self.tfidf = TfidfVectorizer(
            lowercase=True,
            stop_words='english',  # или ['и', 'в', 'на', ...] для русского
            max_features=10000,    # ограничиваем размер словаря
            token_pattern=r'(?u)\b\w\w+\b'
        )
        # Важно: векторизатор должен быть обучен на всех документах, но мы будем применять его к каждому тексту отдельно.
        # Для этого мы будем использовать fit_transform на одном тексте (но это даст только один документ, что неверно).
        # Правильнее – обучить один раз на всех документах при сохранении, но тогда нужно хранить словарь.
        # Альтернатива: использовать HashingVectorizer, чтобы не хранить словарь.
        # Я предлагаю использовать HashingVectorizer – он не требует обучения.
        from sklearn.feature_extraction.text import HashingVectorizer
        self.hashing_vec = HashingVectorizer(
            n_features=10000,
            lowercase=True,
            token_pattern=r'(?u)\b\w\w+\b',
            alternate_sign=False
        )
        # Будем использовать HashingVectorizer для создания разреженных векторов без обучения

    def encode_dense(self, text):
        return self.model.encode(text).tolist()

    def encode_sparse(self, text):
        """
        Генерирует разреженный вектор с помощью HashingVectorizer.
        Возвращает словарь с "indices" и "values" для Qdrant.
        """
        # Преобразуем текст в разреженную матрицу (1 документ)
        sparse_matrix = self.hashing_vec.transform([text])
        # Получаем индексы и значения ненулевых элементов
        indices = sparse_matrix.indices.tolist()
        values = sparse_matrix.data.tolist()
        return {"indices": indices, "values": values}
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
            dense_vec = self.encode_dense(text)
            sparse_vec = self.encode_sparse(text)
            point_id = str(uuid.uuid4())
            points.append({
                "id": point_id,
                "vector": {
                    "dense": dense_vec,
                    "bm25": sparse_vec   # ожидается словарь с "indices" и "values"
                },
                "payload": {"text": text, "metadata": metadata}
            })

        # Проверяем/создаём коллекцию с двумя векторными полями
        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.get(collection_url)
        if resp.status_code == 404:
            create_payload = {
                "vectors": {
                    "dense": {"size": 384, "distance": "Cosine"},
                    "bm25": {"distance": "Cosine"}   # для разреженных векторов
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

    def dense_search(self, query, collection_name="my_docs", limit=20):
        """Только плотный поиск (сохранён для обратной совместимости)"""
        dense_vec = self.encode_dense(query)
        search_payload = {
            "vector": dense_vec,
            "limit": limit,
            "with_payload": True,
            "vector_name": "dense"
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

    def sparse_search(self, query, collection_name="my_docs", limit=20):
        """Только разреженный поиск (BM25)"""
        sparse_vec = self.encode_sparse(query)
        search_payload = {
            "vector": sparse_vec,   # словарь с "indices" и "values"
            "limit": limit,
            "with_payload": True,
            "vector_name": "bm25"
        }
        resp = requests.post(
            f"{self.qdrant_url}/collections/{collection_name}/points/search",
            json=search_payload
        )
        if resp.status_code != 200:
            raise Exception(f"Sparse search failed: {resp.text}")
        data = resp.json()
        results = data.get("result", [])
        return [{
            "text": hit["payload"]["text"],
            "metadata": hit["payload"]["metadata"],
            "score": hit["score"],
            "id": hit["id"]
        } for hit in results]

    def hybrid_search(self, query, collection_name="my_docs", limit=20, 
                      dense_limit=30, sparse_limit=30, rrf_k=60):
        """
        Гибридный поиск: объединяет результаты dense и sparse поиска через RRF.
        """
        dense_results = self.dense_search(query, collection_name, limit=dense_limit)
        sparse_results = self.sparse_search(query, collection_name, limit=sparse_limit)

        # Объединяем по ID, вычисляем RRF
        # Словарь для хранения RRF-скор
        rrf_scores = {}
        # Словарь для хранения информации о точке
        items_by_id = {}

        # Обработка dense результатов
        for rank, item in enumerate(dense_results, start=1):
            item_id = item["id"]
            items_by_id[item_id] = item
            rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1 / (rank + rrf_k)

        # Обработка sparse результатов
        for rank, item in enumerate(sparse_results, start=1):
            item_id = item["id"]
            if item_id not in items_by_id:
                items_by_id[item_id] = item
            rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1 / (rank + rrf_k)

        # Сортируем по RRF
        sorted_ids = sorted(rrf_scores.keys(), key=lambda id: rrf_scores[id], reverse=True)
        # Формируем результат
        result = []
        for idx in sorted_ids[:limit]:
            item = items_by_id[idx]
            # Добавляем RRF-скор в вывод
            item["rrf_score"] = rrf_scores[idx]
            result.append(item)
        return result

    # Оставляем старый метод search_query для обратной совместимости (но он теперь только dense)
    def search_query(self, query, collection_name="my_docs", limit=20, return_text_only=False):
        dense_results = self.dense_search(query, collection_name, limit=limit)
        if return_text_only:
            return [r["text"] for r in dense_results]
        else:
            return dense_results
    def delete_collection(self, collection_name="my_docs"):
        """
        Полностью удаляет коллекцию из Qdrant.
        После этого все данные будут потеряны.
        """
        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        resp = requests.delete(collection_url)
        if resp.status_code == 200:
            print(f"✅ Коллекция '{collection_name}' успешно удалена.")
        elif resp.status_code == 404:
            print(f"⚠️ Коллекция '{collection_name}' не найдена, ничего не делаем.")
        else:
            raise Exception(f"Ошибка при удалении коллекции: {resp.text}")

    def clear_points(self, collection_name="my_docs", batch_size=64):
        """
        Удаляет все точки из коллекции, но сохраняет саму коллекцию.
        """
        collection_url = f"{self.qdrant_url}/collections/{collection_name}"
        # Проверяем, существует ли коллекция
        resp = requests.get(collection_url)
        if resp.status_code == 404:
            print(f"⚠️ Коллекция '{collection_name}' не существует. Ничего не удаляем.")
            return
        elif resp.status_code != 200:
            raise Exception(f"Не удалось получить информацию о коллекции: {resp.text}")

        # Получаем все ID точек
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
            # Удаляем эти точки
            delete_payload = {"points": point_ids}
            delete_resp = requests.post(f"{collection_url}/points/delete", json=delete_payload)
            if delete_resp.status_code != 200:
                raise Exception(f"Ошибка при удалении точек: {delete_resp.text}")
            points_deleted += len(point_ids)
            # Обновляем offset для следующей пачки
            scroll_payload["offset"] = result.get("next_page_offset")
            if not scroll_payload["offset"]:
                break
            print(f"Удалено {points_deleted} точек...")
        print(f"✅ Все точки удалены. Всего удалено: {points_deleted}")