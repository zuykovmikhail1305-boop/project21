"""Tests for presentation multi-agent models and state."""

import pytest
from pydantic import ValidationError

from app.agents.presentation.models import (
    IntentResult,
    ResearchResult,
    SlideOutline,
    PresentationOutline,
    SlideBlock,
    SlideBlockType,
    Slide,
    ReviewIssue,
    ReviewResult,
)
from app.agents.presentation.state import PresentationState


class TestIntentResult:
    """IntentResult model tests."""

    def test_valid_intent(self):
        result = IntentResult(
            title="Выручка Ozon",
            goal="inform",
            audience="investors",
            tone="formal",
            key_topics=["Обзор", "Динамика", "Прогноз"],
            suggested_slide_count=10,
        )
        assert result.title == "Выручка Ozon"
        assert result.goal == "inform"
        assert result.audience == "investors"
        assert result.tone == "formal"
        assert len(result.key_topics) == 3
        assert result.suggested_slide_count == 10

    def test_minimal_intent(self):
        result = IntentResult(
            title="Test",
            goal="inform",
            audience="general",
            tone="neutral",
            key_topics=["topic"],
        )
        assert result.suggested_slide_count == 10  # default
        assert result.constraints == []  # default


class TestResearchResult:
    """ResearchResult model tests."""

    def test_valid_research(self):
        result = ResearchResult(
            summary="Ozon revenue data",
            key_facts=["Revenue grew 20%"],
            statistics=[{"metric": "Revenue", "value": 100}],
            has_sufficient_data=True,
        )
        assert result.has_sufficient_data is True
        assert len(result.key_facts) == 1
        assert len(result.statistics) == 1

    def test_insufficient_data(self):
        result = ResearchResult(
            summary="No data found",
            has_sufficient_data=False,
            data_gaps=["No revenue data for 2024"],
            suggested_queries=["выручка Ozon 2024"],
        )
        assert result.has_sufficient_data is False
        assert len(result.data_gaps) == 1
        assert len(result.suggested_queries) == 1


class TestSlideOutline:
    """SlideOutline model tests."""

    def test_valid_slide_outline(self):
        slide = SlideOutline(
            title="Обзор компании",
            slide_type="content",
            goal="Показать основные показатели компании",
            required_data=["key_fact_1", "stat_1"],
            suggested_layout="bullets",
        )
        assert slide.title == "Обзор компании"
        assert slide.slide_type == "content"
        assert slide.suggested_layout == "bullets"


class TestPresentationOutline:
    """PresentationOutline model tests."""

    def test_valid_outline(self):
        outline = PresentationOutline(
            title="Выручка Ozon",
            total_slides=3,
            narrative_flow="topical",
            slides=[
                SlideOutline(title="Обзор", slide_type="content", goal="Обзор компании"),
                SlideOutline(title="Динамика", slide_type="data", goal="Показать рост"),
                SlideOutline(title="Итоги", slide_type="summary", goal="Резюме"),
            ],
        )
        assert outline.total_slides == 3
        assert len(outline.slides) == 3
        assert outline.slides[0].title == "Обзор"


class TestSlideBlock:
    """SlideBlock model tests with SlideBlockType enum."""

    def test_valid_heading_block(self):
        block = SlideBlock(type=SlideBlockType.HEADING, text="Заголовок", level=1)
        assert block.type == SlideBlockType.HEADING
        assert block.text == "Заголовок"
        assert block.level == 1

    def test_valid_paragraph_block(self):
        block = SlideBlock(type=SlideBlockType.PARAGRAPH, text="Текст")
        assert block.type == SlideBlockType.PARAGRAPH
        assert block.text == "Текст"

    def test_valid_bullet_list_block(self):
        block = SlideBlock(type=SlideBlockType.BULLET_LIST, items=["пункт 1", "пункт 2"])
        assert block.type == SlideBlockType.BULLET_LIST
        assert len(block.items) == 2  # type: ignore[arg-type]

    def test_heading_without_text_raises_error(self):
        with pytest.raises(ValidationError, match="must contain 'text' field"):
            SlideBlock(type=SlideBlockType.HEADING)

    def test_paragraph_without_text_raises_error(self):
        with pytest.raises(ValidationError, match="must contain 'text' field"):
            SlideBlock(type=SlideBlockType.PARAGRAPH)

    def test_bullet_list_without_items_raises_error(self):
        with pytest.raises(ValidationError, match="must contain 'items' list"):
            SlideBlock(type=SlideBlockType.BULLET_LIST)

    def test_chart_without_description_raises_error(self):
        with pytest.raises(ValidationError, match="must contain 'description' field"):
            SlideBlock(type=SlideBlockType.CHART)

    def test_invalid_block_type_from_json_raises_error(self):
        """Invalid block type in JSON should raise ValidationError."""
        with pytest.raises(ValidationError):
            SlideBlock.model_validate_json('{"type": "invalid_type"}')


class TestSlide:
    """Slide model tests with strict validation."""

    def test_valid_slide(self):
        slide = Slide(
            slide_index=0,
            title="Обзор",
            blocks=[
                SlideBlock(type=SlideBlockType.HEADING, text="Обзор компании", level=1),
                SlideBlock(type=SlideBlockType.PARAGRAPH, text="Ozon — крупнейшая e-commerce платформа"),
            ],
            key_message="Ozon лидер рынка",
        )
        assert slide.slide_index == 0
        assert len(slide.blocks) == 2
        assert slide.blocks[0].type == SlideBlockType.HEADING
        assert slide.blocks[0].text == "Обзор компании"

    def test_slide_with_citations(self):
        slide = Slide(
            slide_index=1,
            title="Данные",
            blocks=[SlideBlock(type=SlideBlockType.PARAGRAPH, text="text")],
            key_message="key",
            citations=["doc_1", "doc_2"],
        )
        assert len(slide.citations) == 2

    def test_slide_without_blocks_raises_error(self):
        with pytest.raises(ValidationError, match="List should have at least 1 item"):
            Slide(
                slide_index=0,
                title="Empty",
                blocks=[],
                key_message="key",
            )

    def test_slide_from_json(self):
        """Slide.model_validate_json() should work for LLM responses."""
        json_str = '''{
            "slide_index": 0,
            "title": "Обзор",
            "blocks": [
                {"type": "heading", "level": 1, "text": "Заголовок"},
                {"type": "paragraph", "text": "Текст"}
            ],
            "key_message": "Ключевая мысль",
            "citations": ["doc_1"]
        }'''
        slide = Slide.model_validate_json(json_str)
        assert slide.slide_index == 0
        assert slide.title == "Обзор"
        assert len(slide.blocks) == 2
        assert slide.blocks[0].type == SlideBlockType.HEADING
        assert slide.blocks[0].text == "Заголовок"
        assert slide.blocks[1].type == SlideBlockType.PARAGRAPH
        assert slide.blocks[1].text == "Текст"
        assert slide.key_message == "Ключевая мысль"

    def test_slide_from_json_invalid_block_type(self):
        """Invalid block type in JSON should raise ValidationError."""
        json_str = '''{
            "slide_index": 0,
            "title": "Test",
            "blocks": [{"type": "bargraph"}],
            "key_message": "key"
        }'''
        with pytest.raises(ValidationError):
            Slide.model_validate_json(json_str)

    def test_slide_from_json_missing_blocks(self):
        """Missing blocks should raise ValidationError."""
        json_str = '''{
            "slide_index": 0,
            "title": "Test",
            "blocks": [],
            "key_message": "key"
        }'''
        with pytest.raises(ValidationError, match="List should have at least 1 item"):
            Slide.model_validate_json(json_str)


class TestReviewResult:
    """ReviewResult model tests."""

    def test_clean_review(self):
        review = ReviewResult(
            needs_revision=False,
            overall_score=0.95,
            summary="Отличная презентация",
        )
        assert review.needs_revision is False
        assert review.overall_score == 0.95
        assert len(review.issues) == 0

    def test_review_with_issues(self):
        review = ReviewResult(
            needs_revision=True,
            overall_score=0.4,
            summary="Есть проблемы",
            issues=[
                ReviewIssue(
                    severity="critical",
                    slide_index=2,
                    category="content",
                    description="Слайд без источников",
                    fix_suggestion="Добавить ссылки на источники",
                ),
                ReviewIssue(
                    severity="warning",
                    category="structure",
                    description="Нет слайда с выводами",
                    fix_suggestion="Добавить слайд 'Заключение'",
                ),
            ],
        )
        assert review.needs_revision is True
        assert len(review.issues) == 2
        assert review.issues[0].severity == "critical"
        assert review.issues[0].slide_index == 2


class TestPresentationState:
    """PresentationState TypedDict tests."""

    def test_initial_state(self):
        state: PresentationState = {
            "query": "сделай презентацию о выручке Ozon",
            "user_id": 1,
            "user_groups": [2],
            "intent": None,
            "research": None,
            "outline": None,
            "slides": None,
            "review": None,
            "current_node": "intent",
            "iteration": 0,
            "max_iterations": 3,
            "error": None,
            "artifact_result": None,
        }
        assert state["query"] == "сделай презентацию о выручке Ozon"
        assert state["current_node"] == "intent"
        assert state["iteration"] == 0
        assert state["max_iterations"] == 3

    def test_state_with_intent(self):
        intent = IntentResult(
            title="Выручка Ozon",
            goal="inform",
            audience="investors",
            tone="formal",
            key_topics=["Обзор", "Динамика"],
        )
        state: PresentationState = {
            "query": "сделай презентацию о выручке Ozon",
            "user_id": 1,
            "user_groups": [2],
            "intent": intent,
            "research": None,
            "outline": None,
            "slides": None,
            "review": None,
            "current_node": "intent",
            "iteration": 0,
            "max_iterations": 3,
            "error": None,
            "artifact_result": None,
        }
        assert state["intent"] is not None
        assert state["intent"].title == "Выручка Ozon"
        assert state["intent"].audience == "investors"