"""Детекция дубликатов документов через SimHash/MinHash."""

import hashlib
import re
from typing import Optional


class SimHash:
    """Реализация SimHash для детекции дубликатов текста."""

    def __init__(self, bits: int = 64):
        self.bits = bits

    def _tokenize(self, text: str) -> list[str]:
        """Разбить текст на токены (слова)."""
        text = text.lower()
        tokens = re.findall(r'\w+', text)
        return [t for t in tokens if len(t) > 2]  # отбрасываем короткие слова

    def _hash_token(self, token: str) -> int:
        """Хэш токена."""
        h = hashlib.md5(token.encode('utf-8'))
        return int(h.hexdigest(), 16) & ((1 << self.bits) - 1)

    def compute(self, text: str) -> int:
        """Вычислить SimHash для текста."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0

        v = [0] * self.bits

        for token in tokens:
            h = self._hash_token(token)
            for i in range(self.bits):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1

        fingerprint = 0
        for i in range(self.bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        return fingerprint

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """Расстояние Хэмминга между двумя SimHash."""
        xor = hash1 ^ hash2
        return bin(xor).count('1')

    def similarity(self, hash1: int, hash2: int) -> float:
        """Сходство (0.0 - 1.0) на основе расстояния Хэмминга."""
        distance = self.hamming_distance(hash1, hash2)
        return 1.0 - (distance / self.bits)


class Deduplicator:
    """Детекция дубликатов документов."""

    def __init__(self, threshold: float = 0.85):
        """
        Args:
            threshold: Порог сходства (0.0-1.0), выше которого считаем дубликатом.
        """
        self.simhash = SimHash()
        self.threshold = threshold
        self._fingerprints: dict[int, int] = {}  # document_id -> fingerprint

    def compute_fingerprint(self, text: str) -> int:
        """Вычислить отпечаток текста."""
        return self.simhash.compute(text)

    def is_duplicate(self, text: str, existing_fingerprints: list[int]) -> tuple[bool, float]:
        """Проверить, является ли текст дубликатом существующих."""
        fp = self.compute_fingerprint(text)

        for existing_fp in existing_fingerprints:
            sim = self.simhash.similarity(fp, existing_fp)
            if sim >= self.threshold:
                return True, sim

        return False, 0.0

    def register_document(self, document_id: int, fingerprint: int) -> None:
        """Зарегистрировать отпечаток документа."""
        self._fingerprints[document_id] = fingerprint

    def get_all_fingerprints(self) -> list[int]:
        """Получить все зарегистрированные отпечатки."""
        return list(self._fingerprints.values())