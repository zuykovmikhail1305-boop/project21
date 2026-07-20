# bm25_search.py
from rank_bm25 import BM25Okapi
import re
import os

class BM25Search:
    def __init__(self):
        self.index = None
        self.documents = []  # список словарей с ключами 'text' и 'metadata'

    def build_index(self, data):
        """
        Принимает список чанков (как возвращает Processing.chunking()).
        Строит BM25 индекс и сохраняет тексты и метаданные.
        """
        texts = []
        self.documents = []
        for item in data:
            text, metadata = self._extract_text_and_metadata(item)
            texts.append(self._tokenize(text))
            self.documents.append({"text": text, "metadata": metadata})
        self.index = BM25Okapi(texts)
        print(f"✅ BM25 индекс построен на {len(texts)} документах")

    def search(self, query, limit=10):
        if self.index is None:
            raise ValueError("Индекс не построен. Сначала вызовите build_index()")
        tokenized_query = self._tokenize(query)
        scores = self.index.get_scores(tokenized_query)
        # Сортируем по убыванию
        sorted_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = []
        for idx in sorted_indices[:limit]:
            results.append({
                "text": self.documents[idx]["text"],
                "metadata": self.documents[idx]["metadata"],
                "score": scores[idx],
                "id": f"bm25_{idx}"  # уникальный идентификатор
            })
        return results
    

    def delete_bm25_index(index_file="bm25_index.pkl"):
        """Удаляет файл с сохранённым BM25 индексом."""
        if os.path.exists(index_file):
            os.remove(index_file)
            print(f"✅ BM25 индекс удалён (файл {index_file})")
        else:
            print(f"⚠️ Файл {index_file} не найден, ничего не делаем.")

    @staticmethod
    def _tokenize(text):
        # Простая токенизация (можно улучшить для русского)
        return re.findall(r'\w+', text.lower())

    @staticmethod
    def _extract_text_and_metadata(item):
        if isinstance(item, dict):
            return item.get('text', ''), item.get('metadata', {})
        else:
            text = getattr(item, 'text', '')
            metadata = getattr(item, 'metadata', {})
            return text, metadata