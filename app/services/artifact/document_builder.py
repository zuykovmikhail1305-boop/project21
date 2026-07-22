"""DocumentBuilder: ArtifactPlan → DocumentModel.

Создаёт DocumentModel с stable IDs (section_id, block_id, asset_id),
AssetReference (status=pending) и DependencyGraph.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.artifact.models import (
    ArtifactContext,
    ArtifactPlan,
    AssetReference,
    AssetType,
    Block,
    BlockType,
    BulletListBlock,
    CalloutBlock,
    CalloutStyle,
    ChartBlock,
    CodeBlock,
    Column,
    ColumnsBlock,
    DiagramBlock,
    DiagramEngine,
    DocumentModel,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
    ParagraphBlock,
    QuoteBlock,
    Section,
    TableBlock,
    Theme,
)

logger = logging.getLogger(__name__)


class DocumentBuilder:
    """Строит DocumentModel из ArtifactPlan.

    - Генерирует stable IDs (section_id, block_id, asset_id)
    - Создаёт AssetReference (status=pending) для chart/diagram/formula/table
    - Строит DependencyGraph
    """

    def build(
        self,
        plan: ArtifactPlan,
        context: Optional[ArtifactContext] = None,
        theme: Optional[Theme] = None,
    ) -> DocumentModel:
        """Построить DocumentModel из ArtifactPlan.

        Args:
            plan: План артефакта от LLM (смысловая структура).
            context: Контекст выполнения.
            theme: Тема оформления.

        Returns:
            DocumentModel — единый источник истины.
        """
        doc = DocumentModel(
            title=plan.title,
            artifact_type=plan.artifact_type,
            context=context or ArtifactContext(),
            theme=theme or Theme(),
        )

        for section_data in plan.sections:
            section = self._build_section(section_data)
            doc.sections.append(section)

            # Строим граф зависимостей
            for block in section.blocks:
                doc.dependency_graph.add_edge(
                    block.id, section.id
                )
                for asset_id in block.get_asset_refs():
                    doc.dependency_graph.add_edge(asset_id, block.id)

        logger.info(
            "DocumentModel built: title=%s, sections=%d, blocks=%d",
            doc.title,
            len(doc.sections),
            sum(len(s.blocks) for s in doc.sections),
        )
        return doc

    def _build_section(self, data: dict[str, Any]) -> Section:
        """Построить секцию из данных плана."""
        section = Section(
            title=data.get("title", "Untitled Section"),
        )
        for block_data in data.get("blocks", []):
            block = self._build_block(block_data)
            if block:
                section.blocks.append(block)
        return section

    def _build_block(self, data: dict[str, Any]) -> Optional[Block]:
        """Построить блок из данных плана."""
        block_type_str = data.get("type", "")

        try:
            block_type = BlockType(block_type_str)
        except ValueError:
            logger.warning("Unknown block type: %s", block_type_str)
            return None

        block = Block(block_type=block_type)

        # Заполняем соответствующий блок
        if block_type == BlockType.HEADING:
            block.heading = HeadingBlock(
                level=data.get("level", 1),
                text=data.get("text", ""),
            )
        elif block_type == BlockType.PARAGRAPH:
            block.paragraph = ParagraphBlock(
                text=data.get("text", ""),
            )
        elif block_type == BlockType.TABLE:
            block.table = self._build_table(data)
        elif block_type == BlockType.CHART:
            block.chart = self._build_chart(data)
        elif block_type == BlockType.DIAGRAM:
            block.diagram = self._build_diagram(data)
        elif block_type == BlockType.FORMULA:
            block.formula = self._build_formula(data)
        elif block_type == BlockType.CODE:
            block.code = CodeBlock(
                language=data.get("language", "text"),
                code=data.get("code", ""),
            )
        elif block_type == BlockType.QUOTE:
            block.quote = QuoteBlock(
                text=data.get("text", ""),
                source=data.get("source"),
            )
        elif block_type == BlockType.IMAGE:
            block.image = ImageBlock(
                src=data.get("src", ""),
                alt=data.get("alt", ""),
                width=data.get("width"),
            )
        elif block_type == BlockType.BULLET_LIST:
            block.bullet_list = BulletListBlock(
                items=data.get("items", []),
            )
        elif block_type == BlockType.COLUMNS:
            block.columns = self._build_columns(data)
        elif block_type == BlockType.CALLOUT:
            block.callout = CalloutBlock(
                style=CalloutStyle(data.get("style", "info")),
                text=data.get("text", ""),
            )

        return block

    def _build_table(self, data: dict[str, Any]) -> TableBlock:
        """Построить таблицу с AssetReference."""
        table = TableBlock(
            headers=data.get("headers", []),
            rows=data.get("rows", []),
        )
        # Если есть данные — создаём AssetReference для рендеринга таблицы как изображения
        if table.headers or table.rows:
            table.asset_ref = AssetReference(
                asset_type=AssetType.TABLE,
                source=data.get("data_source", ""),
                spec={
                    "headers": table.headers,
                    "rows": table.rows,
                },
            )
        return table

    def _build_chart(self, data: dict[str, Any]) -> ChartBlock:
        """Построить график с AssetReference.

        ChartBlock содержит ТОЛЬКО смысловое описание, не тип графика.
        """
        chart = ChartBlock(
            description=data.get("description", ""),
            data_source=data.get("data_source", ""),
            columns=data.get("columns", []),
        )
        chart.asset_ref = AssetReference(
            asset_type=AssetType.CHART,
            source=chart.data_source,
            spec={
                "description": chart.description,
                "columns": chart.columns,
            },
        )
        return chart

    def _build_diagram(self, data: dict[str, Any]) -> DiagramBlock:
        """Построить диаграмму с AssetReference."""
        engine_str = data.get("engine", "mermaid")
        try:
            engine = DiagramEngine(engine_str)
        except ValueError:
            engine = DiagramEngine.MERMAID

        diagram = DiagramBlock(
            engine=engine,
            code=data.get("code", ""),
        )
        diagram.asset_ref = AssetReference(
            asset_type=AssetType.DIAGRAM,
            source="",
            spec={
                "engine": engine.value,
                "code": diagram.code,
            },
        )
        return diagram

    def _build_formula(self, data: dict[str, Any]) -> FormulaBlock:
        """Построить формулу с AssetReference."""
        formula = FormulaBlock(
            latex=data.get("latex", ""),
        )
        formula.asset_ref = AssetReference(
            asset_type=AssetType.FORMULA,
            source="",
            spec={"latex": formula.latex},
        )
        return formula

    def _build_columns(self, data: dict[str, Any]) -> ColumnsBlock:
        """Построить колонки (рекурсивно)."""
        columns_data = data.get("columns", [])
        columns = []
        for col_data in columns_data:
            col = Column()
            for block_data in col_data.get("blocks", []):
                block = self._build_block(block_data)
                if block:
                    col.blocks.append(block)
            columns.append(col)
        return ColumnsBlock(columns=columns)