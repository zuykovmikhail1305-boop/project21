from processing import Processing
from embending import Embedding
from find_answer import Find_answer
from agent import Agent

p = Processing('test/text.docx')
data = p.chunking()

e = Embedding()
e.save_to_qdrant(data, collection_name='my_docs')

f = Find_answer('Что такое искусственный интеллект?')
print(f.find_answer())