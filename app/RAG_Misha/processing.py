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
import markdownify
from app.services.gigachat_provider import GigaChatClient 
from docx2pdf import convert
from dotenv import load_dotenv
load_dotenv()


class Processing():
    def __init__(self, doc_path):
        self.original_path = doc_path
        self.pdf_path = None
        # Читаем переменные окружения с дефолтными значениями
        self.chunk_model = os.getenv("CHUNK_MODEL")
        self.chunk_threshold = int(os.getenv("CHUNK_THRESHOLD"))  # если есть переменная, иначе 75

    def _convert_docx_to_pdf(self, docx_path):
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        pdf_path = temp_pdf.name
        convert(docx_path, pdf_path)
        return pdf_path

    def parsing(self):
        if not os.path.exists(self.original_path):
            raise FileNotFoundError(f"Файл не найден: {self.original_path}")

        # Если это docx, конвертируем в pdf
        if self.original_path.lower().endswith('.docx'):
            self.pdf_path = self._convert_docx_to_pdf(self.original_path)
            file_to_parse = self.pdf_path
        else:
            file_to_parse = self.original_path

        # ВАЖНО: Для извлечения таблиц из PDF нужна стратегия 'hi_res'
        # Если файл остался docx, можно оставить 'auto', но для pdf строго 'hi_res'
        strategy = 'hi_res' if file_to_parse.lower().endswith('.pdf') else 'auto'

        elements = partition(
            filename=file_to_parse,
            strategy=strategy,
            languages=['rus', 'eng'],
            # Для hi_res иногда полезно явно указать извлечение таблиц, 
            # но по умолчанию в hi_res оно включено
            extract_image_block_types=["Table"] # Опционально, зависит от версии unstructured
        )

        # Инициализируем клиент ОДИН раз до цикла
        giga = GigaChatClient()

        result = []

        for el in elements:
            if el.category in ["Header", "Footer", "PageBreak"]:
                continue

            clean_text = clean_extra_whitespace(el.text)
            clean_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_text)

            if not clean_text.strip():
                continue
            
            element_data = {
                "category": el.category,
                "text": clean_text,
                "metadata": { 
                    "page_number": el.metadata.page_number if hasattr(el.metadata, 'page_number') else None,
                    "filename": el.metadata.filename if hasattr(el.metadata, 'filename') else None,
                    "filetype": el.metadata.filetype if hasattr(el.metadata, 'filetype') else None,
                    "languages": el.metadata.languages if hasattr(el.metadata, 'languages') else None,
                }
            }

            # Проверяем, что это таблица И есть html-представление И оно не пустое
            if el.category == "Table" and hasattr(el.metadata, 'text_as_html') and el.metadata.text_as_html:
                try:
                    # Конвертируем HTML в Markdown
                    table_md = markdownify.markdownify(el.metadata.text_as_html, heading_style="ATX")
                    
                    # Если таблица огромная, GigaChat может не влезть в контекст. 
                    # Можно добавить проверку длины, но пока оставим как есть.
                    
                    gen_text = giga.generate(
                        prompt=table_md,
                        system_prompt=(
                            'Тебе дана таблица в формате Markdown. Ты должен преобразовать ее в связный текст. '
                            'Тебе необходимо передать весь её смысл: опиши, что в ней происходит, какие переменные, '
                            'какие изменения и т.д. '
                            'Верни только текст, без markdown-форматирования, который должен передавать весь смысл таблицы.'
                        ),
                        temperature=0.8,
                        max_tokens=2048,
                    )

                    full_text = f"{gen_text}\n\nТаблица в структурированном виде:\n{table_md}"
                    element_data["text"] = full_text
                    
                except Exception as e:
                    # Если GigaChat упал (например, из-за длины таблицы), оставляем просто markdown
                    print(f"Ошибка при обработке таблицы через LLM: {e}")
                    element_data["text"] = f"Таблица в структурированном виде:\n{table_md}"

            result.append(element_data)
            
        return result

    def chunking(self, text=None, threshold=None):
        if threshold is None:
            threshold = self.chunk_threshold

        embed_model = HuggingFaceEmbedding(model_name=self.chunk_model)
        splitter = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=threshold,
            include_metadata=True,
        )

        # Для HYDE – оставляем как есть
        if text is not None:
            doc = Document(text=text, metadata={"source": "HYDE"})
            nodes = splitter.get_nodes_from_documents([doc])
            return nodes

        parsed_elements = self.parsing()
        if not parsed_elements:
            return []

        # Общие метаданные (без page_number)
        common_metadata = {
            k: v for k, v in parsed_elements[0]['metadata'].items()
            if k != 'page_number'
        }

        all_nodes = []
        pages = defaultdict(str)   # сюда собираем текст для обычного чанкования

        for el in parsed_elements:
            # --- Таблицы пропускаем через сплиттер, добавляем как есть ---
            if el['category'] == "Table":
                # Формируем текст таблицы. Можно использовать el['text'] или преобразовать text_as_html в Markdown.
                table_text = el['text']  # замените на структурированный вариант, если нужно

                # Метаданные для таблицы
                metadata = {
                    **common_metadata,
                    'page_number': el['metadata'].get('page_number', 'unknown'),
                    'is_table': True,          # маркер, что это таблица
                    'original_metadata': el['metadata']  # если нужен полный доступ
                }
                doc = Document(text=table_text, metadata=metadata)
                all_nodes.append(doc)   # не разбиваем
            else:
                # --- Остальные элементы группируем по страницам для семантического чанкования ---
                page = el['metadata'].get('page_number', 'unknown')
                if page is None:
                    page = 'unknown'
                pages[str(page)] += el['text'] + '\n\n'

        # Чанкуем обычные текстовые блоки
        for page, text in pages.items():
            doc = Document(
                text=text,
                metadata={**common_metadata, 'page_number': page}
            )
            nodes = splitter.get_nodes_from_documents([doc])
            all_nodes.extend(nodes)

        return all_nodes