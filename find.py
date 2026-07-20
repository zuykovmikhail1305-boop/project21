from openai import OpenAI
from embending import Embedding
from bm25_search import BM25Search
from sentence_transformers import CrossEncoder
from processing import Processing  # импортируем для чанкинга

class Find_answer:
    _cross_encoder = None

    def __init__(self, text, bm25_index: BM25Search, history=None):
        self.text = text
        self.bm25 = bm25_index
        self.client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio"
        )
        self.history = history if history is not None else []

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
        response = self.client.chat.completions.create(
            model="qwen2.5-coder-7b-instruct",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=512,
        )
        return response.choices[0].message.content

    def _rrf_fusion_general(self, results_lists, limit=10, k=60):
        """
        Обобщённый RRF для любого числа списков результатов.
        Каждый список должен содержать словари с ключом 'id'.
        Ранг определяется позицией элемента в списке (начиная с 1).
        Возвращает топ-limit элементов с добавленным полем 'rrf_score'.
        """
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

    def find_answer(self, num_results=10, split_hypothesis=True, max_chunks=5):
        """
        Основной метод поиска.
        :param num_results: количество финальных результатов
        :param split_hypothesis: если True, разбивает HYDE-документ на чанки и ищет по каждому
        :param max_chunks: максимальное число чанков (если split_hypothesis=True)
        """
        try:
            hyde = self.HYDE(self.text)
            print("Гипотетический документ:", hyde)

            emb = Embedding()
            all_search_lists = []  # здесь будут все результаты поисков (dense и sparse)

            if split_hypothesis:
                # Разбиваем HYDE-документ на чанки
                proc = Processing("")  # фиктивный путь, но мы не вызываем parsing
                nodes = proc.chunking(text=hyde)
                # Берём не более max_chunks первых чанков
                chunks = [node.text for node in nodes[:max_chunks]]
                print(f"Разбито на {len(chunks)} чанков для поиска.")
                for i, chunk in enumerate(chunks):
                    # Dense поиск по чанку
                    dense_results = emb.dense_search(chunk, limit=20)
                    # Sparse поиск по чанку
                    sparse_results = self.bm25.search(chunk, limit=20)
                    # Добавляем оба списка в общий пул
                    all_search_lists.append(dense_results)
                    all_search_lists.append(sparse_results)
            else:
                # Классический HyDE: один запрос
                dense_results = emb.dense_search(hyde, limit=20)
                sparse_results = self.bm25.search(hyde, limit=20)
                all_search_lists = [dense_results, sparse_results]

            # Объединяем все результаты через RRF
            combined = self._rrf_fusion_general(all_search_lists, limit=num_results)
            return combined

        except Exception as e:
            print(f"Ошибка при поиске: {e}")
            return []

    def reranked(self, query, candidates, top_k=3):
        if not candidates:
            return []
        if Find_answer._cross_encoder is None:
            Find_answer._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
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