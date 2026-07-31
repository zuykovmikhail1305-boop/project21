"""Pydantic models for multi-agent presentation generation pipeline.

Each agent has its own input/output model.
All models use strict Pydantic validation — no manual dict.get() parsing.
Writer Agent uses with_structured_output(Slide) directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# === Block Types ===


class SlideBlockType(str, Enum):
    """Строгий Enum для типов блоков слайда."""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BULLET_LIST = "bullet_list"
    CHART = "chart"
    TABLE = "table"
    QUOTE = "quote"
    CALLOUT = "callout"
    CODE = "code"
    IMAGE = "image"


# === Intent Agent ===


class IntentResult(BaseModel):
    """Result from IntentAgent — presentation goal and audience analysis."""
    title: str = Field(description="Заголовок презентации")
    goal: str = Field(description="Цель презентации: inform | persuade | educate | report")
    audience: str = Field(description="Целевая аудитория: investors | management | team | general")
    tone: str = Field(description="Тональность: formal | neutral | casual")
    key_topics: list[str] = Field(description="Ключевые темы для раскрытия")
    constraints: list[str] = Field(default_factory=list, description="Ограничения (макс слайдов, формат и т.д.)")
    suggested_slide_count: int = Field(default=10, description="Рекомендуемое количество слайдов")


# === Research Agent ===


class ResearchResult(BaseModel):
    """Result from ResearchAgent — gathered context from documents."""
    summary: str = Field(description="Краткое саммари найденных документов")
    key_facts: list[str] = Field(default_factory=list, description="Ключевые факты из документов")
    statistics: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Статистические данные: [{metric, value, period, source}]",
    )
    citations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Цитаты с источниками: [{text, source, doc_id}]",
    )
    has_sufficient_data: bool = Field(default=False, description="Достаточно ли данных для презентации")
    data_gaps: list[str] = Field(default_factory=list, description="Чего не хватает")
    suggested_queries: list[str] = Field(
        default_factory=list,
        description="Уточнённые запросы для повторного поиска (если данных мало)",
    )


# === Planner Agent ===


class SlideOutline(BaseModel):
    """One slide in the presentation outline — structure only, no content."""
    title: str = Field(description="Заголовок слайда")
    slide_type: str = Field(
        description="Тип слайда: title | content | section_divider | data | comparison | summary",
    )
    goal: str = Field(description="Что этот слайд должен коммуницировать (одним предложением)")
    required_data: list[str] = Field(
        default_factory=list,
        description="Ссылки на key_facts или statistics из ResearchResult",
    )
    suggested_layout: str = Field(
        default="content",
        description="Предлагаемый layout: title_only | bullets | chart | two_column | quote | comparison",
    )


class PresentationOutline(BaseModel):
    """Complete presentation outline from PlannerAgent."""
    title: str = Field(description="Заголовок презентации")
    total_slides: int = Field(description="Общее количество слайдов")
    narrative_flow: str = Field(
        description="Нарративный поток: problem-solution | chronological | comparative | topical",
    )
    slides: list[SlideOutline] = Field(description="Список слайдов")


# === Writer Agent ===


class SlideBlock(BaseModel):
    """A single content block within a slide — validated by Pydantic.

    Uses explicit optional fields instead of dict[str, Any] because
    GigaChat's function-calling (with_structured_output) doesn't handle
    dict[str, Any] well — it returns empty objects {} since "any object"
    is a valid dict[str, Any].

    Each block type uses a subset of these fields. The @model_validator
    enforces per-type requirements (e.g. heading must have text).
    """
    type: SlideBlockType = Field(description="Тип блока")

    # Explicit fields instead of dict[str, Any] for GigaChat compatibility
    text: Optional[str] = Field(default=None, description="Текст для heading, paragraph, callout, quote")
    level: Optional[int] = Field(default=None, description="Уровень заголовка (1-3) для heading")
    items: Optional[list[str]] = Field(default=None, description="Элементы списка для bullet_list")
    description: Optional[str] = Field(default=None, description="Описание для chart")
    data_source: Optional[str] = Field(default=None, description="Источник данных для chart")
    headers: Optional[list[str]] = Field(default=None, description="Заголовки колонок для table")
    rows: Optional[list[list[str]]] = Field(default=None, description="Строки таблицы для table")
    style: Optional[str] = Field(default=None, description="Стиль для callout: info | warning | tip")
    source: Optional[str] = Field(default=None, description="Источник для quote")
    code: Optional[str] = Field(default=None, description="Код для code block")
    language: Optional[str] = Field(default=None, description="Язык программирования для code")
    url: Optional[str] = Field(default=None, description="URL изображения для image")
    alt: Optional[str] = Field(default=None, description="Альтернативный текст для image")

    @model_validator(mode="after")
    def validate_block_data(self) -> "SlideBlock":
        """Валидация данных блока в зависимости от типа."""
        if self.type == SlideBlockType.HEADING:
            if not self.text:
                raise ValueError("Heading block must contain 'text' field")
        elif self.type == SlideBlockType.PARAGRAPH:
            if not self.text:
                raise ValueError("Paragraph block must contain 'text' field")
        elif self.type == SlideBlockType.BULLET_LIST:
            if not self.items:
                raise ValueError("Bullet_list block must contain 'items' list")
        elif self.type == SlideBlockType.CHART:
            if not self.description:
                raise ValueError("Chart block must contain 'description' field")
        return self


class Slide(BaseModel):
    """A complete slide with content — validated by Pydantic.

    Writer Agent returns this model directly via with_structured_output(Slide).
    No manual JSON parsing needed.
    """
    slide_index: int = Field(description="Индекс слайда (0-based)")
    title: str = Field(description="Заголовок слайда")
    blocks: list[SlideBlock] = Field(description="Блоки контента слайда (минимум 1)", min_length=1)
    key_message: str = Field(description="Ключевая мысль, которую доносит слайд")
    citations: list[str] = Field(default_factory=list, description="Ссылки на источники")


# === Reviewer Agent ===


class ReviewIssue(BaseModel):
    """An issue found during review."""
    severity: str = Field(description="Серьёзность: critical | warning | suggestion")
    slide_index: Optional[int] = Field(default=None, description="Индекс слайда с проблемой (null = общая проблема)")
    category: str = Field(
        description="Категория: content | structure | data | consistency | design",
    )
    description: str = Field(description="Описание проблемы")
    fix_suggestion: str = Field(description="Предложение по исправлению")


class ReviewResult(BaseModel):
    """Result from ReviewerAgent."""
    needs_revision: bool = Field(description="Требуются ли правки")
    issues: list[ReviewIssue] = Field(default_factory=list, description="Найденные проблемы")
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Общая оценка 0.0-1.0")
    summary: str = Field(default="", description="Общая оценка презентации")