import pickle
from find import Find_answer
from agent import Agent
import os
from dotenv import load_dotenv
load_dotenv()

# Загружаем BM25 индекс
with open("bm25_index.pkl", "rb") as f:
    bm25 = pickle.load(f)

agent = Agent(max_context_messages=10)
history = []  # история диалога для Find_answer

print("Введите вопрос (или 'exit' для выхода, 'clear' для очистки истории):")
while True:
    query = input("\nВы: ")
    if query.lower() in ["exit", "quit", "выход"]:
        break
    if query.lower() == "clear":
        history = []
        print("История очищена.")
        continue

    # Создаём экземпляр Find_answer с текущим вопросом и историей
    finder = Find_answer(query, bm25, history=history)
    candidates = finder.find_answer()

    if candidates:
        # Опциональный реранжинг (берём топ-3)
        best = finder.reranked(query, candidates)
        # Генерируем ответ через агента
        answer, sources = agent.response(query, best, return_sources=True)
        print(f"Агент: {answer}")
        agent.print_sources(sources)

        # Обновляем историю (вопрос и ответ)
        finder.update_history(query, answer)
        history = finder.history
    else:
        print("Не найдено релевантных документов в базе.")