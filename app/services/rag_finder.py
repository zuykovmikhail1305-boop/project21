"""RAG Finder: гибридный поиск (HyDE + BM25 + Dense + Reranking) с использованием GigaChat."""

from langchain_gigachat.chat_models import GigaChat
from app.services.rag_embedder import Embedding
from app.services.bm25_searcher import BM25Search
from app.RAG_Misha.processing import Processing
from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv

load_dotenv()


class Find_answer:
    _cross_encoder = None

    def __init__(self, text, bm25_index: BM25Search, history=None):
        self.text = text
        self.bm25 = bm25_index
        self.history = history if history is not None else []

        # Конфиг для HyDE
        self.hyde_temperature = float(os.getenv("HYDE_TEMPERATURE", "0.7"))
        self.hyde_max_tokens = int(os.getenv("HYDE_MAX_TOKEN", "2048"))

        self.num_results = int(os.getenv("NUM_RESULTS", "10"))
        self.max_chunks = int(os.getenv("MAX_CHUNK_HYDE", "5"))
        self.top_k = int(os.getenv("TOP_RERANKED", "3"))
        self.limit_rrf = int(os.getenv("LIMIT_RRF", "10"))
        self.cross_encoder_model = os.getenv("CROSS_ENC", "cross-encoder/ms-marco-MiniLM-L-6-v2")

        # Используем GigaChat для HyDE генерации
        self.client = GigaChat(
            credentials=os.getenv("GIGACHAT_CREDENTIALS", ""),
            model="GigaChat-2",
            temperature=self.hyde_temperature,
            max_tokens=self.hyde_max_tokens,
            verify_ssl_certs=False
        )

    def _format_history(self):
        if not self.history:
            return "История диалога пуста."
        formatted = []
        for msg in self.history:
            role = "Пользователь" if msg["role"] == "user" else "Ассистент"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)

    def HYDE(self, text):
        history_str = self._format_history()
        system_prompt = f"""Ты — генератор гипотетических документов для поиска (HyDE).
Твоя задача — по запросу пользователя создать короткий, связный текст, который выглядит как фрагмент реального документа, содержащего ответ на этот запрос.

История диалога (для контекста):
{history_str}

Текущий запрос пользователя: {text}

Учитывая историю, сгенерируй гипотетический документ, который отвечает на текущий запрос, но при этом учитывает предыдущие обсуждения.
Стиль текста должен быть максимально приближен к стилю документов в целевой коллекции (например, научная статья, техническая инструкция, энциклопедическая справка).
Фактическая точность не важна — главное — правдоподобие и релевантность теме.
Не добавляй вводных фраз, пояснений или мета-комментариев. Выведи только текст гипотетического документа.
Не учитывай к каком году ты был обучен, если пользователь просит найти документы из года, в котором ты не был ещё обучен, то просто придумывай создавай документ с учётом года пользователя.
Если запрос является уточнением, постарайся включить в документ информацию, связывающую его с предыдущим контекстом."""

        response = self.client.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ])
        return response.content

    def _rrf_fusion_general(self, results_lists, limit=None, k=60):
        """
        Обобщённый RRF для любого числа списков результатов.
        Каждый список должен содержать словари с ключом 'id'.
        Ранг определяется позицией элемента в списке (начиная с 1).
        Возвращает топ-limit элементов с добавленным полем 'rrf_score'.
        """
        if limit is None:
            limit = self.limit_rrf

        rrf_scores = {}
        items_by_id = {}

        for lst in results_lists:
            for rank, item in enumerate(lst, start=1):
                item_id = item["id"]
                if item_id not in items_by_id:
                    items_by_id[item_id] = item
                rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1 / (rank + k)

        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        result = []
        for idx in sorted_ids[:limit]:
            item = items_by_id[idx]
            item["rrf_score"] = rrf_scores[idx]
            result.append(item)
        return result

    def find_answer(self, num_results=None, split_hypothesis=True, max_chunks=None):
        """
        Основной метод поиска.
        :param num_results: количество финальных результатов
        :param split_hypothesis: если True, разбивает HYDE-документ на чанки и ищет по каждому
        :param max_chunks: максимальное число чанков (если split_hypothesis=True)
        """
        if num_results is None:
            num_results = self.num_results
        if max_chunks is None:
            max_chunks = self.max_chunks

        try:
            hyde = self.HYDE(self.text)
            print("Гипотетический документ:", hyde)

            emb = Embedding()
            all_search_lists = []

            if split_hypothesis:
                proc = Processing("")  # фиктивный путь, но мы не вызываем parsing
                nodes = proc.chunking(text=hyde)
                # Берём не более max_chunks первых чанков
                chunks = [node.text for node in nodes[:max_chunks]]
                print(f"Разбито на {len(chunks)} чанков для поиска.")
                for chunk in chunks:
                    dense_results = emb.dense_search(chunk, limit=20)
                    sparse_results = self.bm25.search(chunk, limit=20)
                    all_search_lists.append(dense_results)
                    all_search_lists.append(sparse_results)
            else:
                dense_results = emb.dense_search(hyde, limit=20)
                sparse_results = self.bm25.search(hyde, limit=20)
                all_search_lists = [dense_results, sparse_results]

            combined = self._rrf_fusion_general(all_search_lists, limit=num_results)
            return combined

        except Exception as e:
            print(f"Ошибка при поиске: {e}")
            return []

    def reranked(self, query, candidates, top_k=None):
        if top_k is None:
            top_k = self.top_k

        if not candidates:
            return []
        if Find_answer._cross_encoder is None:
            Find_answer._cross_encoder = CrossEncoder(self.cross_encoder_model)
            print("Кросс-энкодер загружен.")
        pairs = [(query, cand['text']) for cand in candidates]
        rerank_scores = Find_answer._cross_encoder.predict(pairs)
        for cand, new_score in zip(candidates, rerank_scores):
            cand['rerank_score'] = float(new_score)
        ranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)
        return ranked[:top_k]

    def update_history(self, question, answer):
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})

    def clear_history(self):
        self.history = []
