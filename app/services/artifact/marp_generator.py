"""MarpGenerator: DocumentModel → Marp Markdown.

Без LLM. Конвертирует внутреннее представление документа
в Marp-совместимый Markdown для рендеринга через Marp CLI.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.artifact.asset_resolver import AssetResolver
from app.services.artifact.models import (
    AssetReference,
    Block,
    BlockType,
    CalloutStyle,
    DocumentModel,
    Section,
    Theme,
)

logger = logging.getLogger(__name__)


class MarpGenerator:
    """Генерация Marp Markdown из DocumentModel.

    Не использует LLM. Все блоки конвертируются программно.
    """

    def __init__(self, asset_resolver: Optional[AssetResolver] = None):
        self.asset_resolver = asset_resolver or AssetResolver()

    def generate(
        self,
        document: DocumentModel,
    ) -> str:
        """Сгенерировать Marp Markdown из DocumentModel.

        Args:
            document: DocumentModel — единый источник истины.

        Returns:
            Marp-совместимый Markdown.
        """
        lines: list[str] = []

        # YAML front-matter
        lines.extend(self._generate_front_matter(document))

        # Секции → слайды
        for i, section in enumerate(document.sections):
            if i > 0:
                lines.append("---")
            lines.extend(self._generate_section(section, document))

        return "\n".join(lines)

    def _generate_front_matter(self, document: DocumentModel) -> list[str]:
        """Сгенерировать YAML front-matter."""
        theme = document.theme
        lines = [
            "---",
            "marp: true",
            "theme: corporate-dark",
            "paginate: true",
        ]

        # Header
        if theme.header:
            lines.append(f"header: \"{theme.header}\"")

        # Footer
        if theme.footer:
            lines.append(f"footer: \"{theme.footer}\"")

        lines.append("---")
        lines.append("")
        return lines

    def _generate_section(self, section: Section, document: DocumentModel) -> list[str]:
        """Сгенерировать слайд для секции."""
        lines: list[str] = []

        for block in section.blocks:
            block_lines = self._generate_block(block, document)
            lines.extend(block_lines)

        return lines

    def _generate_block(self, block: Block, document: DocumentModel) -> list[str]:
        """Сгенерировать Markdown для блока."""
        if block.block_type == BlockType.HEADING and block.heading:
            prefix = "#" * block.heading.level
            return [f"{prefix} {block.heading.text}", ""]

        elif block.block_type == BlockType.PARAGRAPH and block.paragraph:
            return [f"{block.paragraph.text}", ""]

        elif block.block_type == BlockType.TABLE and block.table:
            return self._generate_table_md(block.table)

        elif block.block_type == BlockType.CHART and block.chart:
            return self._generate_chart_md(block.chart, document)

        elif block.block_type == BlockType.DIAGRAM and block.diagram:
            return self._generate_diagram_md(block.diagram, document)

        elif block.block_type == BlockType.FORMULA and block.formula:
            return self._generate_formula_md(block.formula, document)

        elif block.block_type == BlockType.CODE and block.code:
            return [f"```{block.code.language}", block.code.code, "```", ""]

        elif block.block_type == BlockType.QUOTE and block.quote:
            result = [f"> {block.quote.text}"]
            if block.quote.source:
                result.append(f"> — *{block.quote.source}*")
            result.append("")
            return result

        elif block.block_type == BlockType.IMAGE and block.image:
            alt = block.image.alt or ""
            width = f" w:{block.image.width}" if block.image.width else ""
            return [f"![{alt}]({block.image.src}{width})", ""]

        elif block.block_type == BlockType.BULLET_LIST and block.bullet_list:
            return [f"- {item}" for item in block.bullet_list.items] + [""]

        elif block.block_type == BlockType.COLUMNS and block.columns:
            return self._generate_columns_md(block.columns, document)

        elif block.block_type == BlockType.CALLOUT and block.callout:
            return self._generate_callout_md(block.callout)

        return []

    def _generate_table_md(self, table_block) -> list[str]:
        """Сгенерировать Markdown-таблицу."""
        lines: list[str] = []

        if not table_block.headers and not table_block.rows:
            return []

        # Если есть AssetReference — используем изображение
        if table_block.asset_ref and table_block.asset_ref.status == "resolved":
            asset = table_block.asset_ref.resolved_asset
            if asset:
                return [f"![Table]({asset.file_path})", ""]

        # Иначе — Markdown-таблица
        if table_block.headers:
            lines.append("| " + " | ".join(table_block.headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(table_block.headers)) + " |")

        for row in table_block.rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")

        lines.append("")
        return lines

    def _generate_chart_md(self, chart_block, document: DocumentModel) -> list[str]:
        """Сгенерировать вставку графика."""
        if chart_block.asset_ref and chart_block.asset_ref.status == "resolved":
            asset = chart_block.asset_ref.resolved_asset
            if asset:
                return [f"![{chart_block.description}]({asset.file_path} w:700 h:400)", ""]

        # Placeholder
        return [f"*[Chart: {chart_block.description}]*", ""]

    def _generate_diagram_md(self, diagram_block, document: DocumentModel) -> list[str]:
        """Сгенерировать вставку диаграммы."""
        if diagram_block.asset_ref and diagram_block.asset_ref.status == "resolved":
            asset = diagram_block.asset_ref.resolved_asset
            if asset:
                return [f"![Diagram]({asset.file_path} w:600 h:400)", ""]

        # Placeholder — Mermaid code block
        if diagram_block.engine.value == "mermaid":
            return [f"```mermaid", diagram_block.code, "```", ""]

        return [f"*[Diagram: {diagram_block.engine.value}]*", ""]

    def _generate_formula_md(self, formula_block, document: DocumentModel) -> list[str]:
        """Сгенерировать вставку формулы."""
        if formula_block.asset_ref and formula_block.asset_ref.status == "resolved":
            asset = formula_block.asset_ref.resolved_asset
            if asset:
                return [f"![Formula]({asset.file_path})", ""]

        # Placeholder — LaTeX
        return [f"$${formula_block.latex}$$", ""]

    def _generate_columns_md(self, columns_block, document: DocumentModel) -> list[str]:
        """Сгенерировать двух/трёхколоночный макет."""
        lines: list[str] = []
        num_cols = len(columns_block.columns)

        if num_cols == 0:
            return []

        lines.append('<div class="columns">')
        lines.append("<div>")

        for i, col in enumerate(columns_block.columns):
            if i > 0:
                lines.append("</div>")
                lines.append("<div>")
            for block in col.blocks:
                block_lines = self._generate_block(block, document)
                lines.extend(block_lines)

        lines.append("</div>")
        lines.append("</div>")
        lines.append("")
        return lines

    def _generate_callout_md(self, callout_block) -> list[str]:
        """Сгенерировать callout."""
        style_icons = {
            CalloutStyle.INFO: "ℹ️",
            CalloutStyle.WARNING: "⚠️",
            CalloutStyle.ERROR: "❌",
            CalloutStyle.SUCCESS: "✅",
        }
        icon = style_icons.get(callout_block.style, "ℹ️")
        return [f"> **{icon} {callout_block.style.value.upper()}**", f"> {callout_block.text}", ""]