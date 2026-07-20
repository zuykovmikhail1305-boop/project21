import pickle
from find import Find_answer
from agent import Agent

# Загружаем BM25 индекс (если уже построен) или строим заново
try:
    with open("bm25_index.pkl", "rb") as f:
        bm25 = pickle.load(f)
except FileNotFoundError:
    # Если индекса нет, запускаем построение
    from index_documents import index_all_documents
    bm25 = index_all_documents("test")
    with open("bm25_index.pkl", "wb") as f:
        pickle.dump(bm25, f)

agent = Agent(max_context_messages=10)
print("Введите вопрос (или 'exit' для выхода):")
while True:
    query = input("\nВы: ")
    if query.lower() in ["exit", "quit", "выход"]:
        break

    finder = Find_answer(query, bm25)
    candidates = finder.find_answer(num_results=5)
    # Можно применить реранжинг:
    # candidates = finder.reranked(query, candidates, top_k=3)

    # Формируем ответ
    answer, sources = agent.response(query, candidates, return_sources=True)
    print(f"Агент: {answer}")
    agent.print_sources(sources)