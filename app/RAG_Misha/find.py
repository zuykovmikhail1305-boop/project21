"""RAG Finder: гибридный поиск (HyDE + BM25 + Dense + Reranking) с использованием GigaChat."""

from langchain_gigachat.chat_models import GigaChat
from app.RAG_Misha.embending import Embedding
from app.RAG_Misha.processing import Processing
from sentence_transformers import CrossEncoder
from app.core.config import *
import os


class Find_answer():
    _cross_encoder = None

    @staticmethod
    def _env_to_bool(value, default=False):
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def __init__(self):
        self.history = []

        # Конфиг для HyDE
        self.hyde_temperature = float()
        self.hyde_max_tokens = int(HYDE_MAX_TOKEN)

        self.num_results = int(NUM_RESULTS)
        self.max_chunks = int(MAX_CHUNK_HYDE)
        self.top_k = int(TOP_RERANKED)
        self.limit_rrf = int(LIMIT_RRF)
        self.cross_encoder_model = CROSS_ENC
        self.model_cache_dir = MODEL_CACHE_DIR
        self.local_files_only = LOCAL_FILES_ONLY

        if self.local_files_only:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        # Используем GigaChat для HyDE генерации
        self.client = GigaChat(
            credentials=GIGACHAT_CREDENTIALS,
            model=GIGACHAT_MODEL,
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

    def reranked(self, query, candidates, top_k=None):
        if top_k is None:
            top_k = self.top_k

        if not candidates:
            return []
        if Find_answer._cross_encoder is None:
            ce_kwargs = {
                "local_files_only": self.local_files_only,
            }
            if self.model_cache_dir:
                ce_kwargs["cache_folder"] = self.model_cache_dir

            Find_answer._cross_encoder = CrossEncoder(self.cross_encoder_model, **ce_kwargs)
            print("Кросс-энкодер загружен.")
        pairs = [(query, cand['text']) for cand in candidates]
        rerank_scores = Find_answer._cross_encoder.predict(pairs)
        for cand, new_score in zip(candidates, rerank_scores):
            cand['rerank_score'] = float(new_score)
        ranked = sorted(candidates, key=lambda x: x['rerank_score'], reverse=True)
        return ranked[:top_k]

    
    def find_answer(self, num_results=None, max_chunks=None, query=None, top_k=None):
        """
        Основной метод поиска.
        :param num_results: количество финальных результатов
        :param max_chunks: максимальное число чанков
        :param top_k: количество лучших результатов после reranking
        """
        if num_results is None:
            num_results = self.num_results
        if max_chunks is None:
            max_chunks = self.max_chunks
        if top_k is None:
            top_k = self.top_k

        try:
            if not query:
                return []

            hyde = self.HYDE(query)
            print("Гипотетический документ:", hyde)

            emb = Embedding()
            candidates = []
            texts = []

            proc = Processing()  # фиктивный путь, но мы не вызываем parsing
            nodes = proc.chunking(text=hyde, Hyde=True)
            chunks = [node.text for node in nodes]
            print(f"Разбито на {len(chunks)} чанков для поиска.")

            for chunk in chunks:
                results = emb.hybrid_search(chunk)
                for item in results or []:
                    if isinstance(item, dict) and item.get("text"):
                        candidates.append(item)
                        texts.append(item["text"])

            if not candidates:
                return []

            reranked_results = self.reranked(query, candidates, top_k=num_results)
            if reranked_results:
                return reranked_results[:num_results]

            return [{"text": t} for t in texts[:num_results]]

        except Exception as e:
            print(f"Ошибка при поиске: {e}")
            return []

    def update_history(self, question, answer):
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})

    def clear_history(self):
        self.history = []

    