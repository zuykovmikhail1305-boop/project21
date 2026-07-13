from processing import Processing
from embending import Embedding
from find_answer import Find_answer

p = Processing('test/text.docx')
data = p.chunking()

e = Embedding()
e.save_to_qdrant(data, collection_name='my_docs')

f = Find_answer()
print(f.find_answer('Что такое искусственный интеллект?'))