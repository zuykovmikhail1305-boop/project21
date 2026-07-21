from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()


class Agent:
    def __init__(self, max_context_messages=20):
        # Чтение переменных окружения с преобразованием типов и значениями по умолчанию
        self.agent_api = os.getenv("AGENT_API", "http://localhost:1234/v1")
        self.agent_model = os.getenv("AGENT_MODEL", "qwen2.5-coder-7b-instruct")
        self.agent_temperature = float(os.getenv("AGENT_TEMPERATURE", "0.1"))
        self.agent_max_tokens = int(os.getenv("AGENT_MAX_TOKEN", "8192"))

        self.client = OpenAI(
            base_url=self.agent_api,
            api_key="util"
        )
        self.max_context_messages = max_context_messages
        self.system_prompt = """Ты — точный и полезный ассистент, который отвечает на вопросы, используя только информацию из предоставленного контекста.
Ты никогда не полагаешься на свои собственные знания или обучающие данные, если контекст явно их не подтверждает.

Инструкции:
- Внимательно читай контекст. Пользователь предоставляет набор извлечённых документов или фрагментов. Каждый фрагмент предваряется указанием источника (имя файла и номер страницы).
- Отвечай строго на основе этого контекста. Если ответ полностью подтверждается контекстом, дай чёткий и лаконичный ответ.
- Если в контексте недостаточно информации, скажи прямо: «Предоставленный контекст не содержит достаточно информации для ответа на этот вопрос.»
- Не додумывай, не спекулируй и не используй внешние знания.
- Если в контексте есть противоречивая информация, укажи на противоречие и перечисли конфликтующие источники.
- Сохраняй доброжелательный, вежливый и прямой тон.
- Если в контексте есть таблицы или числовые данные, извлеки из них нужные значения и используй их для ответа. Если можно вычислить ответ на основе данных (суммирование, сравнение), сделай это явно.
- Для уточняющих вопросов продолжай полагаться исключительно на последний предоставленный контекст, если новый не был специально передан.
- Попытайся по максимуму взять информации из чанков, которые тебе предоставляются, допустим, если нет чёткой фразы, которой просит пользователь, то попробуй найти что-то похожее в контексте, который тебе передаётся на ответ.

Формат контекста:
[Начало контекста]
Источник: имя_файла (стр. X)
текст фрагмента
Источник: имя_файла2 (стр. Y)
текст фрагмента
...
[Конец контекста]

Вопрос: ...
Помни: твоя главная цель — точное следование контексту. Точность и прозрачность источников важнее полноты. Если сомневаешься — признай это."""
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.last_context = []

    def response(self, text, context, return_sources=True):
        formatted_chunks = []
        sources = []
        for item in context:
            if isinstance(item, dict):
                chunk_text = item.get('text', '')
                metadata = item.get('metadata', {})
                filename = metadata.get('filename', 'неизвестный документ')
                page = metadata.get('page_number', 'неизвестная страница')
                sources.append({
                    "text": chunk_text,
                    "filename": filename,
                    "page": page,
                    "metadata": metadata
                })
                formatted_chunks.append(f"Источник: {filename} (стр. {page})\n{chunk_text}")
            else:
                formatted_chunks.append(str(item))
                sources.append({"text": str(item), "filename": None, "page": None})

        context_str = "\n\n".join(formatted_chunks) if formatted_chunks else ""

        self.messages.append({
            "role": "user",
            "content": f"[Начало контекста]\n{context_str}\n[Конец контекста]\n\nВопрос: {text}"
        })

        self._trim_history()

        response = self.client.chat.completions.create(
            model=self.agent_model,
            messages=self.messages,
            temperature=self.agent_temperature,
            max_tokens=self.agent_max_tokens,
        )

        assistant_reply = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": assistant_reply})
        self.last_context = sources

        if return_sources:
            return assistant_reply, sources
        else:
            return assistant_reply

    def _trim_history(self):
        system_msg = self.messages[0]
        history = self.messages[1:]
        max_history_msgs = self.max_context_messages * 2
        if len(history) > max_history_msgs:
            history = history[-max_history_msgs:]
        self.messages = [system_msg] + history

    def clear_memory(self):
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def print_sources(self, sources):
        if not sources:
            print("Нет источников.")
            return
        print("\n--- Использованные источники ---")
        for i, src in enumerate(sources, 1):
            print(f"{i}. Файл: {src.get('filename', 'неизвестно')}, стр. {src.get('page', 'неизвестно')}")
            print(f"   Текст: {src['text']}...")
        print("--------------------------------\n")
