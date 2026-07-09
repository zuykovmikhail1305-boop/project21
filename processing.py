from unstructured.partition.auto import partition
from unstructured.cleaners.core import clean_extra_whitespace
from llama_index.core import Document, Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import re

class Processing():
    """Класс для парсинга и чанкинга, полный пайплайн вызывается командной work()
    возврощающая"""
    def __init__(self, doc):
        self.doc = doc

    def parsing(self):
        elements = partition(
            filename=self.doc,
            strategy='auto',
            languages=['rus', 'eng']
        )

        result = []
        for el in elements:
            # Пропускаем служебные элементы (колонтитулы, разрывы страниц)
            if el.category in ["Header", "Footer", "PageBreak"]:
                continue
            
            # Очищаем текст от лишних пробелов и нечитаемых символов
            clean_text = clean_extra_whitespace(el.text)
            clean_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_text)
            
            # Пропускаем пустые элементы
            if not clean_text.strip():
                continue
            
            # Формируем словарь для элемента
            element_data = {
                "category": el.category,
                "text": clean_text,
                "metadata": {
                    "page_number": el.metadata.page_number if el.metadata.page_number else None,
                    "filename": el.metadata.filename if hasattr(el.metadata, 'filename') else None,
                    "filetype": el.metadata.filetype if hasattr(el.metadata, 'filetype') else None,
                    "languages": el.metadata.languages if hasattr(el.metadata, 'languages') else None,
                }
            }
            
            if el.category == "Table" and hasattr(el.metadata, 'text_as_html'):
                element_data["metadata"]["text_as_html"] = el.metadata.text_as_html
            
            result.append(element_data)
        
        return result

    def chunking(self):

        # 1. Получаем элементы
        parsed_elements = self.parsing()
        
        # 2. Фильтруем только NarrativeText и UncategorizedText
        target_categories = ["NarrativeText", "UncategorizedText"]
        filtered_texts = []
        common_metadata = {}
        
        for el in parsed_elements:
            if el["category"] in target_categories:
                filtered_texts.append(el["text"])
                if not common_metadata:
                    common_metadata = el["metadata"].copy()
        
        if not filtered_texts:
            print("⚠️ Нет NarrativeText или UncategorizedText для чанкинга.")
            return []
        
        # 3. Объединяем тексты
        combined_text = "\n\n".join(filtered_texts)
        
        # 4. Создаём Document
        doc = Document(
            text=combined_text,
            metadata=common_metadata
        )
        
        # 5. Эмбеддинг-модель
        embed_model = HuggingFaceEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        # 6. Семантический сплиттер
        splitter = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=50, #ПРОТЕСТИРОВАТЬ РАЗНУЮ ВЕЛИЧИНУ
            include_metadata=True,
        )
        
        # 7. Получаем чанки
        nodes = splitter.get_nodes_from_documents([doc])
        
        # # ----- ВЫВОД РЕЗУЛЬТАТОВ В КОНСОЛЬ -----
        # print(f"\n📄 Документ: {common_metadata.get('filename', 'неизвестно')}")
        # print(f"✅ Создано чанков: {len(nodes)}")
        
        # if not nodes:
        #     print("Чанки не созданы.")
        #     return nodes
        
        # # Выводим первые 5 чанков (или все, если их ≤5)
        # show_count = min(5, len(nodes))
        # print(f"\n--- Показываем первые {show_count} чанков ---\n")
        
        # for i in range(show_count):
        #     node = nodes[i]
        #     print(f"Чанк #{i+1}:")
        #     print(f"  Длина: {len(node.text)} символов")
        #     print(f"  Метаданные: {node.metadata}")
        #     print(f"  Текст:\n{node.text[:300]}{'...' if len(node.text) > 300 else ''}")
        #     print("-" * 50)
        
        # if len(nodes) > 5:
        #     print(f"... и ещё {len(nodes) - 5} чанков (всего {len(nodes)}).")
        
        return nodes

        
p = Processing('test/text.docx')
p.parsing()
print(p.chunking())
        