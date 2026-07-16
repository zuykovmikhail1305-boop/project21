from unstructured.partition.auto import partition
from unstructured.cleaners.core import clean_extra_whitespace
from llama_index.core import Document
from llama_index.core.settings import Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import re
from collections import defaultdict
import os
import tempfile
from docx2pdf import convert


class Processing():
    def __init__(self, doc_path):
        self.original_path = doc_path
        self.pdf_path = None  # будет заполнен после конвертации

    def _convert_docx_to_pdf(self, docx_path):
        """Конвертирует DOCX в PDF и возвращает путь к PDF."""
        # Создаём временный файл с расширением .pdf
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        pdf_path = temp_pdf.name
        # Конвертируем
        convert(docx_path, pdf_path)
        return pdf_path

    def parsing(self):
        # Если файл .docx – конвертируем в PDF
        if not os.path.exists(self.original_path):
                raise FileNotFoundError(f"Файл не найден: {self.original_path}")

        if self.original_path.lower().endswith('.docx'):
            self.pdf_path = self._convert_docx_to_pdf(self.original_path)
            file_to_parse = self.pdf_path
        else:
            file_to_parse = self.original_path

        elements = partition(
            filename=file_to_parse,
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

        if self.pdf_path and os.path.exists(self.pdf_path):
            os.unlink(self.pdf_path)
            self.pdf_path = None
        
        return result

    def chunking(self, text = None):

        embed_model = HuggingFaceEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        splitter = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=25, #ПРОТЕСТИРОВАТЬ РАЗНУЮ ВЕЛИЧИНУ
            include_metadata=True,
        )

        if text is not None:
            doc = Document(text=text, metadata={"source": "HYDE"})  # можно добавить метку
            nodes = splitter.get_nodes_from_documents([doc])
            return nodes

        parsed_elements = self.parsing()

        common_metadata = {
        k: v for k, v in parsed_elements[0]['metadata'].items()
        if k != 'page_number'
        }

        pages = defaultdict(str)
        for el in parsed_elements:
            pages[str(el['metadata']['page_number'])] += el['text']


        all_nodes = []
        for page in pages:
            doc = Document(
                text = pages[page],
                metadata = {**common_metadata, 'page_number': page}
            )

            nodes = splitter.get_nodes_from_documents([doc])
            all_nodes.extend(nodes)
                
        return all_nodes

        

# base_dir = os.path.dirname(os.path.abspath(__file__))  # папка, где лежит скрипт
# file_path = os.path.join(base_dir, 'test', 'text.docx')
# p = Processing(file_path)
# nodes = p.chunking()  # или p.chunking(threshold=90)
# for node in nodes[:3]:
#     print(f"Страница: {node.metadata.get('page_number')}")
#     print(f"Текст: {node.text[:150]}...")