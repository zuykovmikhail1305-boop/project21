from openai import OpenAI
from embending import Embedding
from processing import Processing
from sentence_transformers import CrossEncoder

class Find_answer():

    _cross_encoder = None

    def __init__(self, text):
        self.text = text


    def HYDE(self, text):
        client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio"         
        )
        response = client.chat.completions.create(
            model="qwen2.5-coder-7b-instruct",  # точное имя модели, как в LM Studio
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
    
    def find_answer(self):
        emb = Embedding()
        hyde = self.HYDE(self.text)
        print(hyde)
        # Получаем 10 кандидатов (можно настроить)
        candidates = emb.hybrid_search(hyde, limit=10)
        return candidates

    def reranked(self, query, candidates, top_k=3):
        """
        Переранжирует кандидатов с помощью кросс-энкодера.
        query: строка запроса (оригинальный вопрос пользователя).
        candidates: список словарей от search_query (с ключами text, metadata, score).
        top_k: количество лучших результатов для возврата.
        Возвращает список словарей с обновлёнными score и дополнительным полем 'rerank_score'.
        """
        if not candidates:
            return []

        # Ленивая загрузка кросс-энкодера (один раз для всех вызовов)
        if Find_answer._cross_encoder is None:
            # Можно выбрать более лёгкую модель для скорости
            Find_answer._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("Кросс-энкодер загружен.")

        # Формируем пары (запрос, текст документа)
        pairs = [(query, cand['text']) for cand in candidates]
        # Вычисляем новые скоры (числа от 0 до 1, где 1 — максимальная релевантность)
        rerank_scores = Find_answer._cross_encoder.predict(pairs)

        # Обновляем словари новыми скорами и сортируем
        for cand, new_score in zip(candidates, rerank_scores):
            cand['rerank_score'] = float(new_score)  # может быть и без преобразования

        # Сортируем по убыванию нового скора
        ranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)

        # Возвращаем топ-K
        return ranked[:top_k]
        
        
# from openai import OpenAI
# from embending import Embedding
# from processing import Processing
# from sentence_transformers import CrossEncoder
# import re

# class Find_answer:

#     _cross_encoder = None

#     def __init__(self, text):
#         self.text = text
#         self.client = OpenAI(
#             base_url="http://localhost:1234/v1",
#             api_key="lm-studio"
#         )

#     def _generate_multi_queries(self, original_query, num_queries=5):
#         """
#         Генерирует несколько вариантов формулировки запроса с помощью LLM.
#         Возвращает список строк.
#         """
#         prompt = f"""Ты — ассистент по генерации поисковых запросов. 
# Твоя задача: создать {num_queries} различных формулировок следующего вопроса, чтобы охватить разные аспекты и синонимы.
# Каждый вариант должен быть самостоятельным поисковым запросом, который мог бы привести к релевантным документам.

# Исходный вопрос: {original_query}

# Инструкции:
# - Все варианты должны быть на русском языке.
# - Используй разную лексику, синонимы, перефразирования.
# - Можно расширять или сужать вопрос, но сохраняй основную суть.
# - Ответ должен содержать только список вариантов, каждый с новой строки, без нумерации и пояснений.
# - Не добавляй вводных фраз (например, "Вот варианты:"). Только строки с запросами.

# Пример:
# Исходный вопрос: "Как работает гравитационное линзирование?"
# Варианты:
# Как происходит гравитационное линзирование?
# Объясните механизм гравитационного линзирования.
# Гравитационное линзирование: принцип действия.
# Что такое эффект гравитационной линзы?
# Каков физический процесс гравитационного линзирования?

# Теперь сгенерируй {num_queries} вариантов для вопроса: {original_query}
# """
#         response = self.client.chat.completions.create(
#             model="qwen2.5-coder-7b-instruct",
#             messages=[
#                 {"role": "system", "content": "Ты — полезный ассистент, который генерирует поисковые запросы."},
#                 {"role": "user", "content": prompt}
#             ],
#             temperature=0.7,
#             max_tokens=512,
#         )
#         content = response.choices[0].message.content
#         # Разбиваем на строки и убираем пустые
#         queries = [line.strip() for line in content.split('\n') if line.strip()]
#         # Если получилось меньше, чем запрошено, дополняем оригинальным запросом
#         if len(queries) < num_queries:
#             queries.append(original_query)
#         # Обрезаем до num_queries
#         return queries[:num_queries]

#     def HYDE(self, text):
#         # Оставляем старый метод для обратной совместимости (если нужно)
#         # ... (код без изменений)
#         pass

#     def find_answer(self, num_queries=5, final_top_k=5):
#         """
#         Основной метод поиска с использованием Multi-Query.
#         num_queries: количество генерируемых вариантов запроса.
#         final_top_k: сколько итоговых чанков вернуть.
#         """
#         emb = Embedding()
#         original_query = self.text

#         # 1. Генерируем несколько запросов
#         queries = self._generate_multi_queries(original_query, num_queries)
#         print(f"Сгенерированные запросы: {queries}")

#         all_best = []

#         # 2. Для каждого запроса ищем кандидатов и реранжируем
#         for q in queries:
#             candidates = emb.search_query(q, limit=10)  # 10 кандидатов
#             if candidates:
#                 # Реранжируем, используя оригинальный вопрос
#                 best = self.reranked(original_query, candidates, top_k=1)
#                 if best:
#                     all_best.extend(best)

#         # 3. Удаляем дубликаты по тексту
#         seen = set()
#         unique = []
#         for item in all_best:
#             text = item.get('text', '')
#             if text not in seen:
#                 seen.add(text)
#                 unique.append(item)

#         # 4. Сортируем по реранк-скору (если есть) или по исходному score
#         unique.sort(key=lambda x: x.get('rerank_score', x.get('score', 0)), reverse=True)

#         # 5. Возвращаем топ-K
#         return unique[:final_top_k]

#     def reranked(self, query, candidates, top_k=3):
#         """
#         Переранжирует кандидатов с помощью кросс-энкодера.
#         query: строка запроса (оригинальный вопрос).
#         candidates: список словарей от search_query.
#         top_k: количество лучших результатов для возврата.
#         Возвращает список словарей с обновлённым полем 'rerank_score'.
#         """
#         if not candidates:
#             return []

#         if Find_answer._cross_encoder is None:
#             Find_answer._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
#             print("Кросс-энкодер загружен.")

#         pairs = [(query, cand['text']) for cand in candidates]
#         rerank_scores = Find_answer._cross_encoder.predict(pairs)

#         for cand, new_score in zip(candidates, rerank_scores):
#             cand['rerank_score'] = float(new_score)

#         ranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)
#         return ranked[:top_k]