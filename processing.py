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
from dotenv import load_dotenv
load_dotenv()


class Processing():
    def __init__(self, doc_path):
        self.original_path = doc_path
        self.pdf_path = None
        # Читаем переменные окружения с дефолтными значениями
        self.chunk_model = os.getenv("CHUNK_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.chunk_threshold = int(os.getenv("CHUNK_THRESHOLD", "75"))  # если есть переменная, иначе 75

    def _convert_docx_to_pdf(self, docx_path):
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        pdf_path = temp_pdf.name
        convert(docx_path, pdf_path)
        return pdf_path

    def parsing(self):
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

    def chunking(self, text=None, threshold=None):
        if threshold is None:
            threshold = self.chunk_threshold

        embed_model = HuggingFaceEmbedding(
            model_name=self.chunk_model
        )

        splitter = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=threshold,
            include_metadata=True,
        )

        if text is not None:
            doc = Document(text=text, metadata={"source": "HYDE"})
            nodes = splitter.get_nodes_from_documents([doc])
            return nodes

        parsed_elements = self.parsing()
        if not parsed_elements:
            return []

        common_metadata = {
            k: v for k, v in parsed_elements[0]['metadata'].items()
            if k != 'page_number'
        }

        pages = defaultdict(str)
        for el in parsed_elements:
            page = el['metadata'].get('page_number', 'unknown')
            if page is None:
                page = 'unknown'
            pages[str(page)] += el['text'] + '\n\n'

        all_nodes = []
        for page, text in pages.items():
            doc = Document(
                text=text,
                metadata={**common_metadata, 'page_number': page}
            )
            nodes = splitter.get_nodes_from_documents([doc])
            all_nodes.extend(nodes)

        return all_nodes
