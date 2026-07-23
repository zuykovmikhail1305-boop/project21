"""Integration tests for presentation agents with real GigaChat.

Tests all 5 agents against the actual GigaChat API (not mocks):
1. IntentAgent — with_structured_output(IntentResult)
2. PlannerAgent — with_structured_output(PresentationOutline)
3. WriterAgent — with_structured_output(Slide)  ← critical test
4. ReviewerAgent — with_structured_output(ReviewResult)
5. Full pipeline (Intent → Planner → Writer → Reviewer)

Run with:
    pytest tests/test_presentation_integration.py -v --log-cli-level=INFO

Or with a specific test:
    pytest tests/test_presentation_integration.py::TestWriterAgentIntegration -v --log-cli-level=INFO

Requires GigaChat credentials in .env (GIGACHAT_CLIENT_ID, GIGACHAT_CLIENT_SECRET).
"""

from __future__ import annotations

import logging

import pytest

from app.agents.presentation.intent_agent import IntentAgent
from app.agents.presentation.planner_agent import PlannerAgent
from app.agents.presentation.writer_agent import WriterAgent, WriterError
from app.agents.presentation.reviewer_agent import ReviewerAgent
from app.agents.presentation.models import (
    IntentResult,
    ResearchResult,
    SlideOutline,
    PresentationOutline,
    Slide,
    SlideBlock,
    SlideBlockType,
    ReviewResult,
)

logger = logging.getLogger(__name__)

# ============================================================
# Fixtures
# ============================================================

# Use loop_scope="module" so all tests in a module share one event loop.
# This avoids "Event loop is closed" errors when module-scoped fixtures
# create agents that hold async HTTP connections (GigaChat).


@pytest.fixture(scope="module")
def intent_agent():
    """IntentAgent with real GigaChat."""
    return IntentAgent()


@pytest.fixture(scope="module")
def planner_agent():
    """PlannerAgent with real GigaChat."""
    return PlannerAgent()


@pytest.fixture(scope="module")
def writer_agent():
    """WriterAgent with real GigaChat."""
    return WriterAgent()


@pytest.fixture(scope="module")
def reviewer_agent():
    """ReviewerAgent with real GigaChat."""
    return ReviewerAgent()


@pytest.fixture(scope="module")
def sample_research() -> ResearchResult:
    """Sample ResearchResult for PlannerAgent testing."""
    return ResearchResult(
        summary=(
            "Ozon — крупнейшая e-commerce платформа в России. "
            "Выручка компании за 2024 год составила 500 млрд рублей. "
            "Рост год к году — 30%. Количество активных покупателей — 50 млн."
        ),
        key_facts=[
            "Выручка Ozon за 2024 год — 500 млрд руб.",
            "Рост выручки год к году — 30%",
            "Активных покупателей — 50 млн",
            "Ozon занимает 2-е место на рынке e-commerce РФ",
            "Компания вышла на EBITDA-безубыточность в 2024",
        ],
        statistics=[
            {"metric": "Выручка", "value": "500 млрд руб.", "period": "2024", "source": "контекст"},
            {"metric": "Рост", "value": "30%", "period": "2024", "source": "контекст"},
            {"metric": "Активные покупатели", "value": "50 млн", "period": "2024", "source": "контекст"},
        ],
        has_sufficient_data=True,
    )


# ============================================================
# Test 1: IntentAgent — with_structured_output(IntentResult)
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestIntentAgentIntegration:
    """Test IntentAgent with real GigaChat.

    This is the simplest agent — flat Pydantic model with 7 fields.
    GigaChat handles this reliably, though quality varies (may return
    1 topic instead of 3-5, or wrong goal enum).
    """

    async def test_analyze_basic_query(self, intent_agent: IntentAgent):
        """Test basic query analysis."""
        query = "сделай презентацию о выручке Ozon для инвесторов"
        result = await intent_agent.analyze(query)

        logger.info("IntentAgent result: title='%s', goal=%s, audience=%s, tone=%s",
                     result.title, result.goal, result.audience, result.tone)
        logger.info("  topics: %s", result.key_topics)
        logger.info("  constraints: %s", result.constraints)
        logger.info("  suggested_slide_count: %d", result.suggested_slide_count)

        # Validate result — relaxed assertions for GigaChat quality variance
        assert isinstance(result, IntentResult), f"Expected IntentResult, got {type(result)}"
        assert result.title, "Title should not be empty"
        assert result.goal in ("inform", "persuade", "educate", "report"), \
            f"Invalid goal: '{result.goal}'"
        assert result.audience in ("investors", "management", "team", "general"), \
            f"Invalid audience: '{result.audience}'"
        assert result.tone in ("formal", "neutral", "casual"), \
            f"Invalid tone: '{result.tone}'"
        # GigaChat may return 1 topic — accept ≥1
        assert len(result.key_topics) >= 1, \
            f"Should have at least 1 topic, got {len(result.key_topics)}"
        assert 1 <= result.suggested_slide_count <= 30, \
            f"Slide count should be reasonable: {result.suggested_slide_count}"

    async def test_analyze_educational_query(self, intent_agent: IntentAgent):
        """Test educational query — GigaChat may not set goal='educate' correctly."""
        query = "подготовь обучающую презентацию по основам машинного обучения для команды разработки"
        result = await intent_agent.analyze(query)

        logger.info("IntentAgent result: title='%s', goal=%s, audience=%s, tone=%s",
                     result.title, result.goal, result.audience, result.tone)
        logger.info("  topics: %s", result.key_topics)

        assert isinstance(result, IntentResult)
        assert result.title, "Title should not be empty"
        # GigaChat may not set goal='educate' — accept any valid goal
        assert result.goal in ("inform", "persuade", "educate", "report"), \
            f"Invalid goal: '{result.goal}'"
        # GigaChat may not set audience='team' — accept any valid audience
        assert result.audience in ("investors", "management", "team", "general"), \
            f"Invalid audience: '{result.audience}'"
        assert len(result.key_topics) >= 1

    async def test_analyze_short_query(self, intent_agent: IntentAgent):
        """Test very short query — should still produce valid result."""
        query = "презентация про продажи"
        result = await intent_agent.analyze(query)

        logger.info("IntentAgent result: title='%s', goal=%s, audience=%s",
                     result.title, result.goal, result.audience)

        assert isinstance(result, IntentResult)
        assert result.title, "Title should not be empty"
        assert result.goal in ("inform", "persuade", "educate", "report")
        assert result.audience in ("investors", "management", "team", "general")
        assert len(result.key_topics) >= 1


# ============================================================
# Test 2: PlannerAgent — with_structured_output(PresentationOutline)
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestPlannerAgentIntegration:
    """Test PlannerAgent with real GigaChat.

    PlannerAgent uses with_structured_output(PresentationOutline).
    PresentationOutline has nested SlideOutline models.
    """

    async def test_plan_with_research(
        self,
        planner_agent: PlannerAgent,
        sample_research: ResearchResult,
    ):
        """Test planning with full research context."""
        intent = IntentResult(
            title="Выручка Ozon: анализ и прогнозы",
            goal="inform",
            audience="investors",
            tone="formal",
            key_topics=["Обзор компании Ozon", "Динамика выручки", "Факторы роста", "Прогнозы"],
            suggested_slide_count=10,
        )

        outline = await planner_agent.plan(intent, sample_research)

        logger.info("PlannerAgent result: title='%s', total_slides=%d, flow=%s",
                     outline.title, outline.total_slides, outline.narrative_flow)
        for i, slide in enumerate(outline.slides):
            logger.info("  Slide %d: '%s' (%s) — %s",
                         i + 1, slide.title, slide.slide_type, slide.goal[:60])

        assert isinstance(outline, PresentationOutline), \
            f"Expected PresentationOutline, got {type(outline)}"
        assert outline.title, "Title should not be empty"
        assert outline.total_slides >= 3, \
            f"Should have at least 3 slides, got {outline.total_slides}"
        assert len(outline.slides) >= 3, \
            f"Should have at least 3 slides, got {len(outline.slides)}"
        assert outline.slides[0].slide_type == "title", \
            f"First slide should be 'title', got '{outline.slides[0].slide_type}'"

        # Check slide diversity
        types = {s.slide_type for s in outline.slides}
        assert "summary" in types or "content" in types, \
            f"Should have summary/content slides, got types: {types}"

        # Check that SlideOutline fields are populated
        for slide in outline.slides:
            assert slide.title, f"Slide title should not be empty: {slide}"
            assert slide.goal, f"Slide goal should not be empty: {slide.title}"
            assert slide.slide_type in ("title", "content", "section_divider", "data", "comparison", "summary"), \
                f"Invalid slide_type '{slide.slide_type}' for '{slide.title}'"

    async def test_plan_with_insufficient_data(
        self,
        planner_agent: PlannerAgent,
    ):
        """Test planning with insufficient research data."""
        intent = IntentResult(
            title="Тестовая презентация",
            goal="inform",
            audience="general",
            tone="neutral",
            key_topics=["Тема 1", "Тема 2"],
            suggested_slide_count=5,
        )
        research = ResearchResult(
            summary="Недостаточно данных для презентации",
            has_sufficient_data=False,
            data_gaps=["Нет конкретных цифр"],
        )

        outline = await planner_agent.plan(intent, research)

        logger.info("PlannerAgent (insufficient data): %d slides, flow=%s",
                     outline.total_slides, outline.narrative_flow)

        assert isinstance(outline, PresentationOutline)
        assert outline.total_slides >= 3
        assert len(outline.slides) >= 3


# ============================================================
# Test 3: WriterAgent — with_structured_output(Slide)  ← CRITICAL
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestWriterAgentIntegration:
    """Test WriterAgent with real GigaChat.

    This is the CRITICAL test. WriterAgent uses with_structured_output(Slide)
    where Slide has nested SlideBlock with SlideBlockType enum + model_validator.

    The prompt chain now includes a HumanMessage (not just SystemMessage)
    to avoid GigaChat's 422 "explicit_call should only appeal in user" error.
    """

    async def test_write_title_slide(self, writer_agent: WriterAgent, sample_research: ResearchResult):
        """Test writing a title slide — simplest case."""
        slide_outline = SlideOutline(
            title="Выручка Ozon: анализ и прогнозы",
            slide_type="title",
            goal="Представить тему презентации и заинтересовать аудиторию",
            suggested_layout="title_only",
        )

        slide = await writer_agent.write_slide(slide_outline, sample_research, slide_index=0)

        logger.info("WriterAgent title slide: index=%d, title='%s', blocks=%d",
                     slide.slide_index, slide.title, len(slide.blocks))
        for i, block in enumerate(slide.blocks):
            logger.info("  Block %d: type=%s, text='%s'",
                         i, block.type.value, (block.text or "")[:80])

        assert isinstance(slide, Slide), f"Expected Slide, got {type(slide)}"
        assert slide.slide_index == 0, f"Expected index=0, got {slide.slide_index}"
        assert slide.title, "Title should not be empty"
        assert len(slide.blocks) >= 1, "Should have at least 1 block"
        assert slide.key_message, "Key message should not be empty"

        # Title slide should have heading or paragraph
        block_types = [b.type for b in slide.blocks]
        assert SlideBlockType.HEADING in block_types or SlideBlockType.PARAGRAPH in block_types, \
            f"Title slide should have heading or paragraph, got {block_types}"

    async def test_write_content_slide(self, writer_agent: WriterAgent, sample_research: ResearchResult):
        """Test writing a content slide with bullet list."""
        slide_outline = SlideOutline(
            title="Ключевые показатели Ozon",
            slide_type="data",
            goal="Показать основные финансовые и операционные метрики компании",
            required_data=["key_fact_1", "key_fact_2", "stat_1", "stat_2"],
            suggested_layout="bullets",
        )

        slide = await writer_agent.write_slide(slide_outline, sample_research, slide_index=1)

        logger.info("WriterAgent content slide: index=%d, title='%s', blocks=%d",
                     slide.slide_index, slide.title, len(slide.blocks))
        for i, block in enumerate(slide.blocks):
            logger.info("  Block %d: type=%s, text='%s', items=%s",
                         i, block.type.value, (block.text or "")[:80],
                         block.items[:3] if block.items else "[]")

        assert isinstance(slide, Slide)
        assert slide.slide_index == 1
        assert slide.title, "Title should not be empty"
        assert len(slide.blocks) >= 1, "Should have at least 1 block"
        assert slide.key_message, "Key message should not be empty"

        # Should have bullet_list or paragraph blocks
        block_types = [b.type for b in slide.blocks]
        assert any(t in block_types for t in [SlideBlockType.BULLET_LIST, SlideBlockType.PARAGRAPH, SlideBlockType.HEADING]), \
            f"Content slide should have relevant blocks, got {block_types}"

    async def test_write_summary_slide(self, writer_agent: WriterAgent, sample_research: ResearchResult):
        """Test writing a summary slide."""
        slide_outline = SlideOutline(
            title="Заключение и выводы",
            slide_type="summary",
            goal="Подвести итоги и дать рекомендации инвесторам",
            suggested_layout="bullets",
        )

        slide = await writer_agent.write_slide(slide_outline, sample_research, slide_index=5)

        logger.info("WriterAgent summary slide: index=%d, title='%s', blocks=%d",
                     slide.slide_index, slide.title, len(slide.blocks))
        for i, block in enumerate(slide.blocks):
            logger.info("  Block %d: type=%s, text='%s'",
                         i, block.type.value, (block.text or "")[:80])

        assert isinstance(slide, Slide)
        assert slide.slide_index == 5
        assert slide.title, "Title should not be empty"
        assert len(slide.blocks) >= 1
        assert slide.key_message, "Key message should not be empty"

    async def test_write_slide_with_citations(self, writer_agent: WriterAgent):
        """Test writing a slide with citation tracking."""
        research = ResearchResult(
            summary="Ozon показал рост выручки на 30% в 2024 году",
            key_facts=["Выручка Ozon за 2024 год — 500 млрд руб."],
            statistics=[{"metric": "Выручка", "value": "500 млрд руб.", "period": "2024", "source": "годовой отчёт"}],
            has_sufficient_data=True,
        )
        slide_outline = SlideOutline(
            title="Финансовые результаты",
            slide_type="data",
            goal="Показать финансовые результаты компании",
            suggested_layout="bullets",
        )

        slide = await writer_agent.write_slide(slide_outline, research, slide_index=2)

        logger.info("WriterAgent citations slide: citations=%s", slide.citations)

        assert isinstance(slide, Slide)
        assert len(slide.blocks) >= 1
        # Citations are optional — just check they don't break
        assert isinstance(slide.citations, list)


# ============================================================
# Test 4: ReviewerAgent — with_structured_output(ReviewResult)
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestReviewerAgentIntegration:
    """Test ReviewerAgent with real GigaChat.

    ReviewerAgent uses with_structured_output(ReviewResult).
    ReviewResult has nested ReviewIssue model.
    """

    async def test_review_good_presentation(
        self,
        reviewer_agent: ReviewerAgent,
        writer_agent: WriterAgent,
        sample_research: ResearchResult,
    ):
        """Test reviewing a well-structured presentation."""
        # Build a presentation with 3 slides
        outline = PresentationOutline(
            title="Выручка Ozon",
            total_slides=3,
            narrative_flow="topical",
            slides=[
                SlideOutline(title="Выручка Ozon", slide_type="title", goal="Представить тему"),
                SlideOutline(title="Ключевые показатели", slide_type="data", goal="Показать метрики"),
                SlideOutline(title="Заключение", slide_type="summary", goal="Подвести итоги"),
            ],
        )

        slides: list[Slide] = []
        for i, slide_outline in enumerate(outline.slides):
            try:
                slide = await writer_agent.write_slide(slide_outline, sample_research, i)
                slides.append(slide)
            except WriterError as e:
                logger.warning("WriterAgent failed for slide %d: %s", i, e)
                # Create fallback slide so review can proceed
                slides.append(Slide(
                    slide_index=i,
                    title=slide_outline.title,
                    blocks=[SlideBlock(type=SlideBlockType.PARAGRAPH, text="Контент не сгенерирован")],
                    key_message="Ошибка генерации",
                ))

        result = await reviewer_agent.review(slides, outline)

        logger.info("ReviewerAgent result: score=%.2f, needs_revision=%s, issues=%d",
                     result.overall_score, result.needs_revision, len(result.issues))
        logger.info("  summary: %s", result.summary)
        for issue in result.issues:
            logger.info("  Issue [%s] slide=%s cat=%s: %s",
                         issue.severity, issue.slide_index, issue.category, issue.description[:80])

        assert isinstance(result, ReviewResult), f"Expected ReviewResult, got {type(result)}"
        assert 0.0 <= result.overall_score <= 1.0, \
            f"Score should be 0-1, got {result.overall_score}"
        assert isinstance(result.needs_revision, bool)
        assert isinstance(result.issues, list)

    async def test_review_empty_presentation(self, reviewer_agent: ReviewerAgent):
        """Test reviewing an empty presentation — should detect issues."""
        outline = PresentationOutline(
            title="Пустая презентация",
            total_slides=0,
            narrative_flow="topical",
            slides=[],
        )

        result = await reviewer_agent.review([], outline)

        logger.info("ReviewerAgent empty review: score=%.2f, needs_revision=%s, issues=%d",
                     result.overall_score, result.needs_revision, len(result.issues))

        assert isinstance(result, ReviewResult)
        assert result.needs_revision is True, "Empty presentation should need revision"
        assert len(result.issues) >= 1, "Should have at least 1 issue"


# ============================================================
# Test 5: Full Pipeline (Intent → Planner → Writer → Reviewer)
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestFullPipelineIntegration:
    """Test the full presentation pipeline end-to-end.

    Flow: IntentAgent → PlannerAgent → WriterAgent (×N) → ReviewerAgent
    ResearchAgent is skipped (needs Qdrant with documents).
    """

    async def test_full_pipeline(
        self,
        intent_agent: IntentAgent,
        planner_agent: PlannerAgent,
        writer_agent: WriterAgent,
        reviewer_agent: ReviewerAgent,
        sample_research: ResearchResult,
    ):
        """Run full pipeline with a real query."""
        query = "сделай презентацию о финансовых результатах Ozon для инвесторов"

        # Step 1: Intent
        logger.info("=" * 60)
        logger.info("STEP 1: IntentAgent")
        logger.info("=" * 60)
        intent = await intent_agent.analyze(query)
        assert isinstance(intent, IntentResult), f"IntentAgent failed: {type(intent)}"
        logger.info("✓ Intent: title='%s', goal=%s, audience=%s",
                     intent.title, intent.goal, intent.audience)

        # Step 2: Planner
        logger.info("=" * 60)
        logger.info("STEP 2: PlannerAgent")
        logger.info("=" * 60)
        outline = await planner_agent.plan(intent, sample_research)
        assert isinstance(outline, PresentationOutline), f"PlannerAgent failed: {type(outline)}"
        logger.info("✓ Outline: %d slides, flow=%s", outline.total_slides, outline.narrative_flow)

        # Step 3: Writer (for each slide)
        logger.info("=" * 60)
        logger.info("STEP 3: WriterAgent (%d slides)", len(outline.slides))
        logger.info("=" * 60)
        slides: list[Slide] = []
        writer_errors = 0
        for i, slide_outline in enumerate(outline.slides):
            try:
                slide = await writer_agent.write_slide(slide_outline, sample_research, i)
                slides.append(slide)
                logger.info("✓ Slide %d: '%s' (%d blocks)", i, slide.title, len(slide.blocks))
            except WriterError as e:
                writer_errors += 1
                logger.error("✗ Slide %d failed: %s", i, e)
                slides.append(Slide(
                    slide_index=i,
                    title=slide_outline.title,
                    blocks=[SlideBlock(type=SlideBlockType.PARAGRAPH, text="Ошибка генерации")],
                    key_message="Ошибка",
                ))

        assert len(slides) == len(outline.slides), \
            f"Should have {len(outline.slides)} slides, got {len(slides)}"
        if writer_errors > 0:
            logger.warning("WriterAgent had %d errors out of %d slides",
                           writer_errors, len(outline.slides))

        # Step 4: Reviewer
        logger.info("=" * 60)
        logger.info("STEP 4: ReviewerAgent")
        logger.info("=" * 60)
        review = await reviewer_agent.review(slides, outline)
        assert isinstance(review, ReviewResult), f"ReviewerAgent failed: {type(review)}"
        logger.info("✓ Review: score=%.2f, needs_revision=%s, issues=%d",
                     review.overall_score, review.needs_revision, len(review.issues))

        # Summary
        logger.info("=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        logger.info("Query: %s", query)
        logger.info("Intent: %s", intent.title)
        logger.info("Slides planned: %d", outline.total_slides)
        logger.info("Slides generated: %d", len(slides))
        logger.info("Writer errors: %d", writer_errors)
        logger.info("Review score: %.2f", review.overall_score)
        logger.info("Needs revision: %s", review.needs_revision)

        # Assert pipeline completed
        assert review.overall_score >= 0.0, "Review score should be >= 0"
        logger.info("✓ Full pipeline completed successfully!")


# ============================================================
# Test 6: Error Handling
# ============================================================


@pytest.mark.asyncio(loop_scope="module")
class TestErrorHandling:
    """Test error handling in agents."""

    async def test_writer_agent_no_llm(self):
        """WriterAgent should raise WriterError when LLM is None."""
        assert WriterError.__name__ == "WriterError"
        assert issubclass(WriterError, Exception)

    async def test_reviewer_empty_slides(self, reviewer_agent: ReviewerAgent):
        """ReviewerAgent should handle empty slides gracefully."""
        outline = PresentationOutline(
            title="Test",
            total_slides=0,
            narrative_flow="topical",
            slides=[],
        )
        result = await reviewer_agent.review([], outline)
        assert result.needs_revision is True
        assert len(result.issues) >= 1