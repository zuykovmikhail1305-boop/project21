"""Citation service: formatting and managing citations for LLM answers."""

from typing import Optional


class CitationFormatter:
    """Formats citations from search results into human-readable references."""

    @staticmethod
    def format_citation(citation: dict) -> str:
        """Format a single citation dict into a readable string.

        Args:
            citation: dict with keys: document_id, chunk_index, score, document_name (optional)

        Returns:
            Formatted citation string like "[1] Документ #3, чанк #5 (релевантность: 0.92)"
        """
        doc_id = citation.get("document_id", "?")
        chunk_idx = citation.get("chunk_index", "?")
        score = citation.get("score", 0)
        doc_name = citation.get("document_name")

        if doc_name:
            return (
                f"[Doc #{doc_id}] «{doc_name}», "
                f"фрагмент #{chunk_idx} "
                f"(релевантность: {score:.2f})"
            )
        return (
            f"[Doc #{doc_id}] "
            f"фрагмент #{chunk_idx} "
            f"(релевантность: {score:.2f})"
        )

    @staticmethod
    def format_citations(citations: list[dict]) -> str:
        """Format a list of citations into a numbered block.

        Args:
            citations: List of citation dicts.

        Returns:
            Formatted string like:
            "**Источники:**\n1. [Doc #3] «Отчёт Q3», фрагмент #5 (0.92)\n2. ..."
        """
        if not citations:
            return ""

        lines = ["**Источники:**"]
        for i, c in enumerate(citations, 1):
            lines.append(f"{i}. {CitationFormatter.format_citation(c)}")

        return "\n".join(lines)

    @staticmethod
    def format_citations_html(citations: list[dict]) -> str:
        """Format citations as HTML for SSE streaming.

        Args:
            citations: List of citation dicts.

        Returns:
            HTML string with citation links.
        """
        if not citations:
            return ""

        parts = ['<div class="citations mt-4 p-3 bg-surface-variant/30 rounded-lg">',
                 '<p class="text-sm font-medium text-on-surface-variant mb-2">📚 Источники:</p>',
                 '<ol class="list-decimal list-inside space-y-1">']

        for c in citations:
            doc_id = c.get("document_id", "?")
            doc_name = c.get("document_name", f"Документ №{doc_id}")
            score = c.get("score", 0)
            parts.append(
                f'<li class="text-sm text-on-surface-variant">'
                f'<a href="/documents/{doc_id}" class="text-primary hover:underline">'
                f'{doc_name}</a> — релевантность: {score:.0%}'
                f'</li>'
            )

        parts.append('</ol></div>')
        return "\n".join(parts)


class CitationBuilder:
    """Builds citation metadata from search results for storage in ChatMessage."""

    @staticmethod
    def build_citations(
        chunks: list[dict],
        document_map: Optional[dict[int, str]] = None,
    ) -> list[dict]:
        """Build citation list from search result chunks.

        Args:
            chunks: List of chunk dicts from vector store search.
            document_map: Optional mapping of document_id → document_name.

        Returns:
            List of citation dicts suitable for ChatMessage.citations JSON field.
        """
        citations = []
        seen = set()

        for chunk in chunks:
            doc_id = chunk.get("document_id")
            chunk_idx = chunk.get("chunk_index")

            # Deduplicate by (doc_id, chunk_idx)
            key = (doc_id, chunk_idx)
            if key in seen:
                continue
            seen.add(key)

            citation = {
                "document_id": doc_id,
                "chunk_index": chunk_idx,
                "score": float(chunk.get("rerank_score", chunk.get("score", 0))),
                "content_preview": chunk.get("content", "")[:200],
            }

            if document_map and doc_id in document_map:
                citation["document_name"] = document_map[doc_id]

            citations.append(citation)

        return citations