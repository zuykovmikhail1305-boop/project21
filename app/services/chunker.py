"""Асинхронный чанкер текста.

Использует Processing из RAG_Misha в thread pool (CPU-bound).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.RAG_Misha.processing import Processing

logger = logging.getLogger(__name__)


class AsyncTextChunker:
    """Асинхронный чанкер текста.

    CPU-bound операция Processing.chunking() выполняется в thread pool,
    чтобы не блокировать event loop.
    """

    def __init__(self) -> None:
        self._processor: Processing | None = None

    def _get_processor(self) -> Processing:
        """Get or create processor (lazy init)."""
        if self._processor is None:
            self._processor = Processing()
        return self._processor

    async def chunk_file(
        self,
        file_path: str,
        doc_id: int,
        threshold: int | None = None,
    ) -> list[dict[str, Any]]:
        """Parse and chunk a file asynchronously.

        Args:
            file_path: Path to the file.
            doc_id: Document ID.
            threshold: Optional chunk threshold percentile.

        Returns:
            List of chunks with text and metadata.
        """
        loop = asyncio.get_event_loop()
        processor = self._get_processor()
        nodes = await loop.run_in_executor(
            None,
            lambda: processor.chunking(
                original_path=file_path,
                doc_id=doc_id,
                threshold=threshold,
            ),
        )
        return self._nodes_to_dicts(nodes)

    async def chunk_text(
        self,
        text: str,
        threshold: int | None = None,
    ) -> list[dict[str, Any]]:
        """Chunk raw text asynchronously (HYDE mode).

        Args:
            text: Text to chunk.
            threshold: Optional chunk threshold percentile.

        Returns:
            List of chunks with text and metadata.
        """
        loop = asyncio.get_event_loop()
        processor = self._get_processor()
        nodes = await loop.run_in_executor(
            None,
            lambda: processor.chunking(
                text=text,
                threshold=threshold,
                Hyde=True,
            ),
        )
        return self._nodes_to_dicts(nodes)

    @staticmethod
    def _nodes_to_dicts(nodes: list) -> list[dict[str, Any]]:
        """Convert llama-index Node objects to dicts."""
        results = []
        for node in nodes:
            results.append({
                "text": node.text,
                "metadata": node.metadata or {},
                "node_id": node.node_id,
            })
        return results
