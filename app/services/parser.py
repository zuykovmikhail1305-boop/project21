"""Асинхронный парсер документов.

Использует Processing из RAG_Misha в thread pool (CPU-bound).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.RAG_Misha.processing import Processing

logger = logging.getLogger(__name__)


class AsyncDocumentParser:
    """Асинхронный парсер документов.

    CPU-bound операция Processing.parsing() выполняется в thread pool,
    чтобы не блокировать event loop.
    """

    def __init__(self) -> None:
        self._processor: Processing | None = None

    def _get_processor(self) -> Processing:
        """Get or create processor (lazy init)."""
        if self._processor is None:
            self._processor = Processing()
        return self._processor

    async def parse(self, file_path: str, doc_id: int) -> list[dict[str, Any]]:
        """Parse a document asynchronously.

        Args:
            file_path: Path to the file to parse.
            doc_id: Document ID for metadata.

        Returns:
            List of parsed elements with text and metadata.
        """
        loop = asyncio.get_event_loop()
        processor = self._get_processor()
        return await loop.run_in_executor(
            None, processor.parsing, file_path, doc_id
        )
