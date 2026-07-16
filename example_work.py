from processing import Processing
from embending import Embedding
from find_answer import Find_answer
from agent import Agent

# p = Processing('test/text.docx')
# data = p.chunking()

# e = Embedding()
# e.save_to_qdrant(data, collection_name='my_docs')

# f = Find_answer('Что такое искусственный интеллект?')
# print(f.find_answer())

emb = Embedding()

# # 1. Полностью удалить коллекцию (все данные)
# emb.delete_collection("my_docs")

# 2. Очистить точки, но оставить коллекцию
# emb.clear_points("my_docs")

# links = ['test/2025_12_26.pdf', 
#         'test/o_tekushchey_situacii_v_rossiyskoy_ekonomike_itogi_2024_goda.pdf',
#         'test/tekushhee-sostoyanie-rossijskoj-ekonomiki-i-prognoz-v-2020-2024-gg.-i-na-period-do-2035-g.pdf']

# for link in links:
#     p = Processing(link)
#     data = p.chunking()
#     emb = Embedding()
#     emb.save_to_qdrant(data)

while True:
    query = input("Вы: ")
    if query.lower() in ["exit", "quit"]:
        break

    finder = Find_answer(query)                         # список словарей с 'text' и 'metadata'
    candidates = finder.find_answer()                     # получаем 10 кандидатов
    best = finder.reranked(query, candidates, top_k=3) 

    agent = Agent()
    answer, sources = agent.response(query, best, return_sources=True)

    print(f"Агент: {answer}")
    agent.print_sources(sources)  # выведет информацию об источниках

