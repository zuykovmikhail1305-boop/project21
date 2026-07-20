from openai import OpenAI
from embending import Embedding
from bm25_search import BM25Search
from sentence_transformers import CrossEncoder

class Find_answer:
    # Кросс-энкодер загружается один раз для всех экземпляров
    _cross_encoder = None

    def __init__(self, text, bm25_index: BM25Search):
        """
        :param text: исходный вопрос пользователя
        :param bm25_index: экземпляр BM25Search с построенным индексом
        """
        self.text = text
        self.bm25 = bm25_index
        self.client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio"
        )

    def HYDE(self, text):
        """
        Генерирует гипотетический документ на основе вопроса.
        """
        response = self.client.chat.completions.create(
            model="qwen2.5-coder-7b-instruct",
            messages=[
                {"role": "system", "content": """Вот системный промт на русском языке для модели, реализующей технику **HyDE (Hypothetical Document Embeddings)**.  
Он настраивает модель на генерацию гипотетического документа, который затем будет использован для поиска релевантных фрагментов в базе знаний.

---

Ты — генератор гипотетических документов.  
Твоя задача: по запросу пользователя создать короткий, связный текст, который выглядит как фрагмент реального документа, содержащего ответ на этот запрос.

### Инструкции
1. **Сгенерируй воображаемый документ** (от нескольких предложений до небольшого абзаца), который прямо отвечает на вопрос пользователя.
2. **Стиль текста** должен быть максимально приближен к стилю документов в целевой коллекции (например, научная статья, техническая инструкция, новостная заметка, энциклопедическая справка). Используй характерную лексику, термины и структуру предложений.
3. **Фактическая точность не важна** — ты можешь придумывать детали. Главное — правдоподобие и релевантность теме, чтобы векторное представление этого текста было близко к реальным релевантным документам.
4. **Не добавляй вводных фраз, пояснений или мета-комментариев.** Выведи только текст гипотетического документа.
5. Если запрос содержит специфическую терминологию, активно используй её в ответе.  
Если запрос на общую тему — создай текст, который мог бы быть абзацем из учебника или справочника по этой теме.

### Формат работы
Пользователь задаёт вопрос. Ты выдаёшь один или несколько абзацев гипотетического документа.

**Пример**  
Запрос: *«Как работает гравитационное линзирование?»*  
Ответ модели:
> Гравитационное линзирование — это астрономическое явление, при котором свет от далёкого источника (например, галактики или квазара) искривляется под действием гравитационного поля массивного объекта, расположенного на луче зрения. В результате наблюдатель может видеть множественные изображения источника, дуги или кольца Эйнштейна. Эффект описывается общей теорией относительности и широко используется для изучения распределения тёмной материи в скоплениях галактик.

Такой текст будет закодирован в векторное представление и использован для поиска похожих реальных документов."""},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=512,
        )
        return response.choices[0].message.content

    def _rrf_fusion(self, dense_results, sparse_results, limit=10, k=60):
        """
        Объединяет результаты плотного и разреженного поиска через Reciprocal Rank Fusion.
        :param dense_results: список словарей от dense_search
        :param sparse_results: список словарей от bm25.search
        :param limit: количество финальных результатов
        :param k: параметр сглаживания RRF (обычно 60)
        :return: список словарей с текстом, метаданными, скором, id и добавленным 'rrf_score'
        """
        rrf_scores = {}
        items_by_id = {}

        # Обработка dense результатов
        for rank, item in enumerate(dense_results, start=1):
            item_id = item["id"]
            items_by_id[item_id] = item
            rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1 / (rank + k)

        # Обработка sparse результатов
        for rank, item in enumerate(sparse_results, start=1):
            item_id = item["id"]
            if item_id not in items_by_id:
                items_by_id[item_id] = item
            rrf_scores[item_id] = rrf_scores.get(item_id, 0) + 1 / (rank + k)

        # Сортируем по убыванию RRF-скора
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        result = []
        for idx in sorted_ids[:limit]:
            item = items_by_id[idx]
            item["rrf_score"] = rrf_scores[idx]
            result.append(item)
        return result

    def find_answer(self, num_results=10):
        """
        Основной метод: генерирует HYDE, выполняет плотный и BM25 поиск,
        объединяет результаты через RRF и возвращает топ-N кандидатов.
        :param num_results: количество финальных результатов
        :return: список словарей с текстом, метаданными, скорами и id
        """
        # 1. Генерация гипотетического документа
        hyde = self.HYDE(self.text)
        print("Гипотетический документ:", hyde)

        # 2. Плотный поиск (dense) через Qdrant
        emb = Embedding()
        dense_results = emb.dense_search(hyde, limit=20)  # больше кандидатов для RRF

        # 3. BM25 поиск через внешний индекс
        sparse_results = self.bm25.search(hyde, limit=20)

        # 4. Объединение через RRF
        combined = self._rrf_fusion(dense_results, sparse_results, limit=num_results)
        return combined

    def reranked(self, query, candidates, top_k=3):
        """
        Переранжирует кандидатов с помощью кросс-энкодера.
        :param query: исходный вопрос пользователя
        :param candidates: список словарей от find_answer (с ключами text, metadata, score, id)
        :param top_k: количество лучших результатов для возврата
        :return: список словарей с добавленным полем 'rerank_score', отсортированный по убыванию
        """
        if not candidates:
            return []

        # Ленивая загрузка кросс-энкодера (один раз для всех вызовов)
        if Find_answer._cross_encoder is None:
            Find_answer._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("Кросс-энкодер загружен.")

        # Формируем пары (запрос, текст документа)
        pairs = [(query, cand['text']) for cand in candidates]
        rerank_scores = Find_answer._cross_encoder.predict(pairs)

        # Обновляем словари новыми скорами
        for cand, new_score in zip(candidates, rerank_scores):
            cand['rerank_score'] = float(new_score)

        # Сортируем по убыванию нового скора
        ranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)
        return ranked[:top_k]