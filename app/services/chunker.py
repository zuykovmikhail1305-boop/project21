"""Разбиение текста на чанки с сохранением метаданных."""

from typing import Optional


class ChunkResult:
    """Результат чанкинга — один фрагмент текста."""

    def __init__(
        self,
        content: str,
        chunk_index: int,
        chunk_type: str = "text",
        metadata: Optional[dict] = None,
        token_count: int = 0,
    ):
        self.content = content
        self.chunk_index = chunk_index
        self.chunk_type = chunk_type
        self.metadata = metadata or {}
        self.token_count = token_count


class TextChunker:
    """Разбиение текста на чанки заданного размера с перекрытием."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100,
    ):
        """
        Args:
            chunk_size: Максимальное количество символов в чанке.
            chunk_overlap: Перекрытие между чанками (в символах).
            min_chunk_size: Минимальный размер чанка (меньшие отбрасываются).
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_text(
        self,
        text: str,
        base_metadata: Optional[dict] = None,
    ) -> list[ChunkResult]:
        """Разбить текст на чанки."""
        if not text or len(text.strip()) < self.min_chunk_size:
            return []

        chunks = []
        start = 0
        index = 0

        while start < len(text):
            # Определяем конец чанка
            end = start + self.chunk_size

            if end >= len(text):
                end = len(text)
            else:
                # Пытаемся разбить по границе предложения или абзаца
                end = self._find_split_point(text, start, end)

            chunk_text = text[start:end].strip()
            if len(chunk_text) >= self.min_chunk_size:
                chunks.append(ChunkResult(
                    content=chunk_text,
                    chunk_index=index,
                    chunk_type="text",
                    metadata={
                        **(base_metadata or {}),
                        "char_start": start,
                        "char_end": end,
                    },
                    token_count=self._estimate_tokens(chunk_text),
                ))
                index += 1

            # Двигаемся с перекрытием
            start = end - self.chunk_overlap if end < len(text) else len(text)

        return chunks

    def _find_split_point(self, text: str, start: int, end: int) -> int:
        """Найти оптимальную точку разбиения (по границе абзаца или предложения)."""
        search_start = max(start, end - self.chunk_overlap)

        # Ищем двойной перенос строки (граница абзаца)
        paragraph_break = text.rfind("\n\n", search_start, end)
        if paragraph_break != -1:
            return paragraph_break + 2

        # Ищем одиночный перенос строки
        line_break = text.rfind("\n", search_start, end)
        if line_break != -1:
            return line_break + 1

        # Ищем конец предложения
        for punct in [". ", "! ", "? "]:
            pos = text.rfind(punct, search_start, end)
            if pos != -1:
                return pos + 2

        # Ищем пробел
        space = text.rfind(" ", search_start, end)
        if space != -1:
            return space + 1

        return end

    def _estimate_tokens(self, text: str) -> int:
        """Грубая оценка количества токенов (4 символа ≈ 1 токен)."""
        return len(text) // 4


def chunk_document(
    text: str,
    metadata: Optional[dict] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[ChunkResult]:
    """Удобная функция для чанкинга документа."""
    chunker = TextChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return chunker.chunk_text(text, base_metadata=metadata)