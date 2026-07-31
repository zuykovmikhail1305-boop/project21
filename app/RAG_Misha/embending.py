import os
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from app.core.config import *


class Embedding:
    @staticmethod
    def _env_to_bool(value, default=False):
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def __init__(self):
        self.emb_model = os.getenv("EMB_MODEL", "sergeyzh/rubert-tiny-turbo")
        self.qdrant_url = os.getenv("QDRANT_BASE", "http://localhost:6333")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "document_chunks")
        self.sparse_model = os.getenv("SPARSE_MODEL", "Qdrant/bm25")
        self.model_cache_dir = os.getenv("MODEL_CACHE_DIR")
        self.fastembed_cache_dir = os.getenv("FASTEMBED_CACHE_DIR") or self.model_cache_dir
        self.local_files_only = self._env_to_bool(os.getenv("LOCAL_FILES_ONLY"), default=False)

        if self.local_files_only:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        st_kwargs = {
            "local_files_only": self.local_files_only,
        }
        if self.model_cache_dir:
            st_kwargs["cache_folder"] = self.model_cache_dir

        self.model = SentenceTransformer(self.emb_model, **st_kwargs)
        self.vector_size = int(os.getenv("QDRANT_VECTOR_SIZE", "312"))
        self.client = QdrantClient(
            url=self.qdrant_url,
            api_key=os.getenv("QDRANT_API_KEY"),
        )
        sparse_kwargs = {}
        if self.fastembed_cache_dir:
            sparse_kwargs["cache_dir"] = self.fastembed_cache_dir
        self.client.set_sparse_model(self.sparse_model, **sparse_kwargs)
        self.sparse_vector_name = self.client.get_sparse_vector_field_name() or "fast-sparse-bm25"

    def encode_dense(self, text):
        return self.model.encode(text).tolist()

    def encode_sparse(self, text):
        sparse_vector = next(
            self.client._sparse_embed_documents(
                [text],
                embedding_model_name=self.sparse_model,
            )
        )
        return sparse_vector

    def _extract_text_and_metadata(self, item):
        if isinstance(item, dict):
            return item.get("text", ""), item.get("metadata", {})

        text = getattr(item, "text", "")
        metadata = getattr(item, "metadata", {})
        return text, metadata

    def _ensure_collection(self, collection_name):
        if self.client.collection_exists(collection_name):
            return

        # Задаём имя для разреженного поля один раз
        if not hasattr(self, 'sparse_vector_name') or self.sparse_vector_name is None:
            self.sparse_vector_name = "fast-sparse-bm25"

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                self.sparse_vector_name: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                )
            },
        )

    def save_to_qdrant(self, data, collection_name=None, batch_size=64):
        if collection_name is None:
            collection_name = self.collection_name

        self._ensure_collection(collection_name)

        points = []
        for item in data:
            text, metadata = self._extract_text_and_metadata(item)
            dense_vec = self.encode_dense(text)
            sparse_vec = self.encode_sparse(text)
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "dense": dense_vec,
                        self.sparse_vector_name: sparse_vec,
                    },
                    payload={"text": text, "metadata": metadata},
                )
            )

        total = len(points)
        for i in range(0, total, batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(collection_name=collection_name, points=batch)
            print(f"Сохранено {min(i + batch_size, total)} из {total}")
        print(f"✅ Все {total} точек сохранены в коллекцию '{collection_name}'")

    def get_chunks_by_doc_id(self, doc_id, text_key="text"):
        """
        Возвращает список текстов чанков, принадлежащих документу с указанным doc_id.

        :param doc_id: идентификатор документа (хранится в metadata.doc_id)
        :param text_key: ключ в payload, где хранится текст чанка (по умолчанию "text")
        :param limit: размер батча для scroll (по умолчанию 100)
        :return: list[str] – список текстовых фрагментов
        """
        collection_name = self.collection_name
        filter_obj = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.doc_id",
                    match=models.MatchValue(value=doc_id)
                )
            ]
        )

        all_texts = []
        offset = None

        while True:
            points, offset = self.client.scroll(
                collection_name=collection_name,
                offset=offset,
                with_payload=True,
                limit=100,
                with_vectors=False,
                filter=filter_obj
            )

            if not points:
                break

            for point in points:
                # Извлекаем текст из payload
                text = point.payload.get(text_key)
                if text is not None and isinstance(text, str):
                    all_texts.append(text)
                else:
                    pass

        return all_texts

    def hybrid_search(self, query, limit=int(NUM_RESULTS)):
        collection_name = self.collection_name

        dense_vec = self.encode_dense(query)
        sparse_vec = self.encode_sparse(query)
        result = self.client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=limit,
                ),
                models.Prefetch(
                    query=sparse_vec,
                    using=self.sparse_vector_name,
                    limit=limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        hits = getattr(result, "points", result)
        return [{
            "text": hit.payload.get("text", "") if hit.payload else "",
            "metadata": hit.payload.get("metadata", {}) if hit.payload else {},
            "score": hit.score,
            "id": hit.id,
        } for hit in hits]

    def delete_collection(self, collection_name=None):
        if collection_name is None:
            collection_name = self.collection_name

        if self.client.collection_exists(collection_name):
            self.client.delete_collection(collection_name)
            print(f"✅ Коллекция '{collection_name}' успешно удалена.")
        else:
            print(f"⚠️ Коллекция '{collection_name}' не найдена, ничего не делаем.")

    def clear_points(self, collection_name=None, batch_size=64):
        if collection_name is None:
            collection_name = self.collection_name

        if not self.client.collection_exists(collection_name):
            print(f"⚠️ Коллекция '{collection_name}' не существует. Ничего не удаляем.")
            return

        offset = None
        points_deleted = 0
        while True:
            points, next_offset = self.client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            if not points:
                break

            point_ids = [p.id for p in points]
            self.client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(points=point_ids),
            )
            points_deleted += len(point_ids)
            offset = next_offset
            if offset is None:
                break
            print(f"Удалено {points_deleted} точек...")
        print(f"✅ Все точки удалены. Всего удалено: {points_deleted}")