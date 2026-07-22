"""Pydantic модели для новой архитектуры генерации артефактов v2.

DocumentModel — единый источник истины.
AssetReference (lazy) → Asset (resolved).
ArtifactContext — контекст выполнения.
Theme — корпоративный стиль.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# === Identified Mixin ===


class Identified(BaseModel):
    """Базовый класс для всех элементов со stable ID."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])


# === Enums ===


class AssetType(str, Enum):
    """Типы ассетов."""
    IMAGE = "image"
    SVG = "svg"
    CHART = "chart"
    DIAGRAM = "diagram"
    TABLE = "table"
    LOGO = "logo"
    ICON = "icon"
    FORMULA = "formula"
    VIDEO = "video"


class BlockType(str, Enum):
    """Типы блоков документа."""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CHART = "chart"
    DIAGRAM = "diagram"
    FORMULA = "formula"
    CODE = "code"
    QUOTE = "quote"
    IMAGE = "image"
    BULLET_LIST = "bullet_list"
    COLUMNS = "columns"
    CALLOUT = "callout"


class CalloutStyle(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class DiagramEngine(str, Enum):
    MERMAID = "mermaid"
    DRAWIO = "drawio"
    PLANTUML = "plantuml"


class ArtifactStatus(str, Enum):
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


# === ArtifactContext ===


class ArtifactContext(BaseModel):
    """Контекст выполнения — влияет на весь pipeline."""
    language: str = "ru"
    company: str = ""
    timezone: str = "Europe/Moscow"
    currency: str = "RUB"
    number_format: str = "#,##0.00"
    citation_style: str = "gost"
    theme_name: str = "corporate"
    locale: str = "ru-RU"
    date_format: str = "DD.MM.YYYY"


# === Theme ===


class ThemeFonts(BaseModel):
    heading: str = "Arial"
    body: str = "Arial"
    size_heading: int = 28
    size_body: int = 14


class ThemeColors(BaseModel):
    primary: str = "#0052CC"
    secondary: str = "#7A869A"
    background: str = "#FFFFFF"
    text: str = "#172B4D"
    accent: str = "#00B8D9"
    success: str = "#36B37E"
    warning: str = "#FFAB00"
    error: str = "#FF5630"


class SlideLayout(BaseModel):
    """Кастомный layout слайда."""
    name: str
    template: str  # Marp-совместимый HTML/Markdown шаблон


class Theme(BaseModel):
    """Тема оформления — корпоративный стиль."""
    name: str = "corporate"
    display_name: str = "Corporate"
    fonts: ThemeFonts = Field(default_factory=ThemeFonts)
    colors: ThemeColors = Field(default_factory=ThemeColors)
    margins: dict[str, int] = Field(default_factory=lambda: {"top": 20, "bottom": 20, "left": 30, "right": 30})
    logo: Optional[str] = None  # путь к логотипу
    header: Optional[str] = None  # HTML/Markdown для верхнего колонтитула
    footer: Optional[str] = None  # HTML/Markdown для нижнего колонтитула
    chart_palette: list[str] = Field(
        default_factory=lambda: ["#0052CC", "#00B8D9", "#36B37E", "#FFAB00", "#FF5630", "#6554C0", "#7A869A"]
    )
    slide_layouts: dict[str, SlideLayout] = Field(default_factory=dict)


# === Asset System (Lazy) ===


class AssetReference(BaseModel):
    """Ссылка на ассет — до генерации (lazy)."""
    asset_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    asset_type: AssetType
    status: str = "pending"  # pending | resolved | error
    source: str = ""  # описание источника данных
    spec: dict[str, Any] = Field(default_factory=dict)  # параметры для генерации
    resolved_asset: Optional[ArtifactAsset] = None  # заполняется после генерации


class ArtifactAsset(BaseModel):
    """Ассет — после генерации (resolved)."""
    asset_id: str
    asset_type: AssetType
    name: str
    mime_type: str
    file_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


# === Block Types ===


class HeadingBlock(BaseModel):
    level: int = Field(ge=1, le=6, default=1)
    text: str


class ParagraphBlock(BaseModel):
    text: str


class TableBlock(BaseModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    asset_ref: Optional[AssetReference] = None


class ChartBlock(BaseModel):
    """ChartBlock содержит ТОЛЬКО смысловое описание, не тип графика."""
    description: str  # "Sales by month"
    data_source: str  # "table_1"
    columns: list[str] = Field(default_factory=list)  # ["month", "sales"]
    asset_ref: Optional[AssetReference] = None


class DiagramBlock(BaseModel):
    engine: DiagramEngine = DiagramEngine.MERMAID
    code: str
    asset_ref: Optional[AssetReference] = None


class FormulaBlock(BaseModel):
    latex: str
    asset_ref: Optional[AssetReference] = None


class CodeBlock(BaseModel):
    language: str
    code: str


class QuoteBlock(BaseModel):
    text: str
    source: Optional[str] = None


class ImageBlock(BaseModel):
    src: str
    alt: str = ""
    width: Optional[int] = None


class BulletListBlock(BaseModel):
    items: list[str] = Field(default_factory=list)


class ColumnsBlock(BaseModel):
    columns: list[Column] = Field(default_factory=list)


class Column(BaseModel):
    blocks: list[Block] = Field(default_factory=list)


class CalloutBlock(BaseModel):
    style: CalloutStyle = CalloutStyle.INFO
    text: str


# === Block (union) ===


class Block(Identified):
    """Универсальный блок документа. Ровно одно из полей заполнено."""
    block_type: BlockType

    heading: Optional[HeadingBlock] = None
    paragraph: Optional[ParagraphBlock] = None
    table: Optional[TableBlock] = None
    chart: Optional[ChartBlock] = None
    diagram: Optional[DiagramBlock] = None
    formula: Optional[FormulaBlock] = None
    code: Optional[CodeBlock] = None
    quote: Optional[QuoteBlock] = None
    image: Optional[ImageBlock] = None
    bullet_list: Optional[BulletListBlock] = None
    columns: Optional[ColumnsBlock] = None
    callout: Optional[CalloutBlock] = None

    def get_asset_refs(self) -> list[str]:
        """Вернуть список asset_id, на которые ссылается блок."""
        refs = []
        for field_name in ["table", "chart", "diagram", "formula"]:
            field = getattr(self, field_name, None)
            if field and field.asset_ref:
                refs.append(field.asset_ref.asset_id)
        return refs


# === Section ===


class Section(Identified):
    """Секция документа."""
    title: str
    blocks: list[Block] = Field(default_factory=list)


# === Dependency Graph ===


class DependencyGraph(BaseModel):
    """Граф зависимостей между блоками и ассетами."""
    edges: list[tuple[str, str]] = Field(default_factory=list)  # (from_id, to_id)

    def add_edge(self, from_id: str, to_id: str) -> None:
        """Добавить зависимость: from → to."""
        self.edges.append((from_id, to_id))

    def get_affected(self, changed_id: str) -> set[str]:
        """Вернуть все ID, которые нужно перегенерировать при изменении changed_id."""
        affected: set[str] = set()
        # BFS по графу
        queue = [changed_id]
        while queue:
            current = queue.pop(0)
            for from_id, to_id in self.edges:
                if from_id == current and to_id not in affected:
                    affected.add(to_id)
                    queue.append(to_id)
        return affected

    def get_dependents(self, target_id: str) -> set[str]:
        """Вернуть все ID, от которых зависит target_id."""
        dependents: set[str] = set()
        queue = [target_id]
        while queue:
            current = queue.pop(0)
            for from_id, to_id in self.edges:
                if to_id == current and from_id not in dependents:
                    dependents.add(from_id)
                    queue.append(from_id)
        return dependents


# === DocumentModel (единый источник истины) ===


class DocumentModel(BaseModel):
    """Единственный источник истины для артефакта."""
    title: str
    artifact_type: str  # pdf, pptx, docx, md, html
    context: ArtifactContext = Field(default_factory=ArtifactContext)
    theme: Theme = Field(default_factory=Theme)
    sections: list[Section] = Field(default_factory=list)
    dependency_graph: DependencyGraph = Field(default_factory=DependencyGraph)

    def get_block(self, block_id: str) -> Optional[Block]:
        """Найти блок по ID."""
        for section in self.sections:
            for block in section.blocks:
                if block.id == block_id:
                    return block
        return None

    def get_section(self, section_id: str) -> Optional[Section]:
        """Найти секцию по ID."""
        for section in self.sections:
            if section.id == section_id:
                return section
        return None

    def get_all_asset_refs(self) -> list[AssetReference]:
        """Собрать все AssetReference из документа."""
        refs: list[AssetReference] = []
        for section in self.sections:
            for block in section.blocks:
                for field_name in ["table", "chart", "diagram", "formula"]:
                    field = getattr(block, field_name, None)
                    if field and field.asset_ref:
                        refs.append(field.asset_ref)
        return refs


# === ArtifactPlan (смысловая структура от LLM) ===


class ArtifactPlan(BaseModel):
    """План артефакта от LLM — ТОЛЬКО смысловая структура, без указания типов графиков."""
    title: str
    artifact_type: str = "pdf"
    sections: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Список секций. Каждая: {title, blocks: [{type, text, description, data_source, ...}]}",
    )
    reasoning: str = ""


# === Validation ===


class CheckResult(BaseModel):
    """Результат одной проверки валидатора."""
    check_name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Результат валидации."""
    passed: bool
    checks: list[CheckResult] = Field(default_factory=list)
    errors: list[CheckResult] = Field(default_factory=list)

    def add_check(self, result: CheckResult) -> None:
        self.checks.append(result)
        if not result.passed:
            self.errors.append(result)
        self.passed = len(self.errors) == 0


# === Render Result ===


class RenderResult(BaseModel):
    """Результат рендеринга артефакта."""
    success: bool
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None