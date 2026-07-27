"""Parser - совместимая версия для старого кода (обёртка над document_processor.py)."""

from app.services.document_processor import Processing
import os


class DocumentParser:
    """Document parser - обёртка для обратной совместимости."""

    def __init__(self, file_path):
        self.file_path = file_path
        self.processor = Processing(file_path)

    def parse(self):
        """Парсить документ."""
        return self.processor.parsing()
