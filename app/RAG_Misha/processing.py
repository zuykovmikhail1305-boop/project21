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
import shutil
from app.services.gigachat_provider import GigaChatClient
from docx2pdf import convert
from docforge import DocumentProcessor, DocForgeException
from dotenv import load_dotenv
from bs4 import BeautifulSoup
load_dotenv()


class Processing():
    def __init__(self, doc_path):
        self.original_path = doc_path
        # Читаем переменные окружения
        self.chunk_model = os.getenv("CHUNK_MODEL")
        self.chunk_threshold = int(os.getenv("CHUNK_THRESHOLD", 75))
        self.docforge = DocumentProcessor(verbose=False)

    def _convert_docx_to_pdf(self, docx_path):
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        pdf_path = temp_pdf.name
        convert(docx_path, pdf_path)
        return pdf_path

    def _has_tesseract(self):
        return shutil.which("tesseract") is not None

    def _ocr_with_docforge(self, input_path):
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        output_path = temp_pdf.name

        result = self.docforge.ocr_pdf(
            input_path,
            output_path,
            language='rus+eng',
            dpi=300,
            layout_mode='precise',
        )

        if isinstance(result, dict) and not result.get('success', True):
            raise RuntimeError(result.get('message') or result.get('error') or 'DocForge OCR failed')

        return output_path

    def _normalize_tag_name(self, value):
        value = str(value or "")
        value = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "_", value, flags=re.UNICODE)
        value = value.strip("_").lower()
        return value or "column"

    def _extract_table_grid(self, block):
        html = getattr(block.metadata, "text_as_html", None)
        rows = []

        if html:
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")
            if table:
                for tr in table.find_all("tr"):
                    cells = []
                    for cell in tr.find_all(["th", "td"]):
                        cell_text = clean_extra_whitespace(cell.get_text(" ", strip=True))
                        cell_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', cell_text)
                        cells.append(cell_text)
                    if any(cell.strip() for cell in cells):
                        rows.append(cells)

        if rows:
            return rows

        raw_text = clean_extra_whitespace(getattr(block, "text", "") or "")
        raw_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw_text)
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                cells = [clean_extra_whitespace(part) for part in line.split("|")]
            else:
                cells = [line]
            if any(cell.strip() for cell in cells):
                rows.append(cells)

        return rows

    def _build_tagrag_table(self, block):
        rows = self._extract_table_grid(block)
        page_number = block.metadata.page_number if hasattr(block.metadata, "page_number") else None

        if not rows:
            fallback_text = clean_extra_whitespace(getattr(block, "text", "") or "")
            return {
                "text": f"[table]\n[page_number] {page_number or 'unknown'}\n[raw]\n{fallback_text}",
                "rows": [],
                "headers": [],
            }

        headers = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []

        if not data_rows:
            headers = [f"column_{index + 1}" for index in range(len(headers))]
            data_rows = rows

        table_lines = [
            "[table]",
            f"[page_number] {page_number or 'unknown'}",
            f"[columns] {len(headers)}",
            f"[rows] {len(data_rows)}",
        ]

        row_documents = []
        for row_index, row in enumerate(data_rows, start=1):
            row_map = {}
            row_lines = [f"[row_{row_index}]"]
            for col_index, cell_value in enumerate(row):
                header = headers[col_index] if col_index < len(
                    headers) and headers[col_index] else f"column_{col_index + 1}"
                tag = self._normalize_tag_name(header)
                cell_value = clean_extra_whitespace(cell_value)
                row_map[tag] = cell_value
                row_lines.append(f"[{tag}] {cell_value}")

            row_text = "\n".join(row_lines)
            row_documents.append({
                "row_index": row_index,
                "text": row_text,
                "values": row_map,
            })
            table_lines.append(row_text)

        return {
            "text": "\n\n".join(table_lines),
            "rows": row_documents,
            "headers": headers,
        }

    def parsing(self):
        if not os.path.exists(self.original_path):
            raise FileNotFoundError(f"Файл не найден: {self.original_path}")

        temp_files = []
        file_to_parse = self.original_path

        # Если это docx, конвертируем в PDF, затем прогоняем через DocForge OCR.
        if self.original_path.lower().endswith('.docx'):
            self.pdf_path = self._convert_docx_to_pdf(self.original_path)
            temp_files.append(self.pdf_path)
            file_to_parse = self.pdf_path

        # DocForge используется как OCR/нормализация перед извлечением блоков.
        if file_to_parse.lower().endswith('.pdf') and self._has_tesseract():
            try:
                ocr_pdf_path = self._ocr_with_docforge(file_to_parse)
                temp_files.append(ocr_pdf_path)
                file_to_parse = ocr_pdf_path
            except (DocForgeException, Exception) as e:
                print(f"⚠️ DocForge OCR не сработал, использую исходный PDF: {e}")

        # После DocForge OCR PDF уже должен содержать текстовый слой, поэтому unstructured
        # можно запускать без OCR-стратегии. Если tesseract недоступен, берём fast.
        is_pdf = file_to_parse.lower().endswith('.pdf')
        strategy = 'auto' if is_pdf and self._has_tesseract() else 'fast' if is_pdf else 'auto'

        elements = partition(
            filename=file_to_parse,
            strategy=strategy,
            languages=['rus', 'eng'],
            extract_image_block_types=["Table"],
        )

        result_list = []

        try:
            for block in elements:
                if block.category in ["Header", "Footer", "PageBreak"]:
                    continue

                raw_text = getattr(block, 'text', '') or ''
                clean_text = clean_extra_whitespace(raw_text)
                clean_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean_text)

                if not clean_text.strip():
                    continue

                element_data = {
                    "category": block.category,
                    "text": clean_text,
                    "metadata": {
                        "page_number": block.metadata.page_number if hasattr(block.metadata, 'page_number') else None,
                        "filename": block.metadata.filename if hasattr(block.metadata, 'filename') else None,
                        "filetype": block.metadata.filetype if hasattr(block.metadata, 'filetype') else None,
                        "languages": block.metadata.languages if hasattr(block.metadata, 'languages') else None,
                    }
                }

                if block.category == "Table":
                    tagrag_table = self._build_tagrag_table(block)
                    element_data["text"] = tagrag_table["text"]
                    element_data["metadata"]["is_table"] = True
                    element_data["metadata"]["table_headers"] = tagrag_table["headers"]
                    element_data["metadata"]["table_rows"] = tagrag_table["rows"]

                result_list.append(element_data)

            return result_list
        finally:
            for temp_file in temp_files:
                try:
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass

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
                table_rows = el['metadata'].get('table_rows', [])

                if table_rows:
                    for row in table_rows:
                        metadata = {
                            **common_metadata,
                            'page_number': el['metadata'].get('page_number', 'unknown'),
                            'is_table': True,
                            'row_index': row.get('row_index'),
                            'table_headers': el['metadata'].get('table_headers', []),
                            'original_metadata': el['metadata'],
                        }
                        doc = Document(text=row.get('text', ''), metadata=metadata)
                        all_nodes.append(doc)
                else:
                    metadata = {
                        **common_metadata,
                        'page_number': el['metadata'].get('page_number', 'unknown'),
                        'is_table': True,
                        'original_metadata': el['metadata']
                    }
                    doc = Document(text=el['text'], metadata=metadata)
                    all_nodes.append(doc)
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
