"""Text Chunker - совместимая версия для старого кода (обёртка над document_processor.py)."""

from app.services.document_processor import Processing
import os


class TextChunker:
    """Text chunker - обёртка для обратной совместимости."""

    def __init__(self, model_name=None, threshold=None):
        self.processor = Processing("")
        if model_name:
            self.processor.chunk_model = model_name
        if threshold:
            self.processor.chunk_threshold = threshold

    def chunk_text(self, text: str, **kwargs):
        """Разбить текст на чанки."""
        nodes = self.processor.chunking(text=text)
        return [{"text": node.text, "metadata": node.metadata} for node in nodes]

    def chunk_file(self, file_path: str, **kwargs):
        """Разбить файл на чанки."""
        self.processor.original_path = file_path
        nodes = self.processor.chunking()
        return [{"text": node.text, "metadata": node.metadata} for node in nodes]
