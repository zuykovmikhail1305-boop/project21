"""Базовые абстракции и Pydantic модели для генерации артефактов."""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class SandboxResult(BaseModel):
    """Результат выполнения кода графика в sandbox."""
    success: bool
    output_files: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class ChartPlan(BaseModel):
    """План одного графика."""
    chart_index: int
    chart_type: Literal["line", "bar", "pie", "scatter", "heatmap", "table"]
    title: str
    data_source: str  # описание, какие данные использовать
    engine: Literal["matplotlib", "plotly"] = "matplotlib"


class SectionPlan(BaseModel):
    """План одного раздела артефакта."""
    title: str
    description: str
    requires_chart: Optional[int] = None  # индекс графика из charts


class ArtifactPlan(BaseModel):
    """Полный план структуры артефакта."""
    title: str
    artifact_type: Literal["pdf", "pptx", "docx", "md", "html"]
    chart_engine: Literal["matplotlib", "plotly"] = "matplotlib"
    sections: list[SectionPlan] = Field(default_factory=list)
    charts: list[ChartPlan] = Field(default_factory=list)


class ArtifactContent(BaseModel):
    """Контент для рендерера — результат генерации."""
    title: str
    artifact_type: str
    markdown_content: str  # Marp-совместимый Markdown
    chart_paths: list[str] = Field(default_factory=list)  # пути к PNG/SVG
    interactive_chart_paths: list[str] = Field(default_factory=list)  # пути к HTML (plotly)


class RenderResult(BaseModel):
    """Результат рендеринга артефакта."""
    success: bool
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    error: Optional[str] = None