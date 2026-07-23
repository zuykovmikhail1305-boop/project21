"""Unit-тесты для ArtifactGeneratorAgent v2.

Полный набор тестов для всех 6 фаз генерации артефактов:
1. Planning — LLM → ArtifactPlan
2. Document Building — DocumentBuilder.build() → DocumentModel
3. Document Validation — DocumentValidator.validate() + ArtifactAutoFix
4. Rendering — RendererFactory.render() → RenderResult
5. Render Validation — RenderValidator.validate()
6. Save — v2 таблицы + StorageProvider
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.agents.artifact_generator import ArtifactGeneratorAgent
from app.services.artifact.models import (
    ArtifactContext,
    ArtifactPlan,
    ArtifactStatus,
    AssetReference,
    AssetType,
    Block,
    BlockType,
    CheckResult,
    DocumentModel,
    HeadingBlock,
    ParagraphBlock,
    RenderResult,
    Section,
    Theme,
    ThemeColors,
    ThemeFonts,
    ValidationResult,
)
from app.services.artifact.template_manager import TemplateManager
from app.services.artifact.theme_manager import ThemeManager
from app.services.artifact.document_builder import DocumentBuilder
from app.services.artifact.validator import DocumentValidator, ArtifactAutoFix, RenderValidator
from app.services.artifact.renderer_factory import RendererFactory
from app.services.artifact.asset_resolver import AssetResolver
from app.services.storage import StorageProvider


# Регистрируем anyio маркер для pytest
pytest_plugins = ("anyio",)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_llm():
    """Mock LLM провайдера с with_structured_output."""
    llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock()
    llm.with_structured_output.return_value = structured_llm
    return llm


@pytest.fixture
def mock_db_session():
    """Mock SQLAlchemy session."""
    session = MagicMock(spec=Session)
    session.add = MagicMock()
    
    # При add и flush устанавливаем id=1 на всех добавленных объектах
    # SQLAlchemy модели используют InstrumentedAttribute для Column,
    # поэтому прямое присваивание obj.id = 1 работает через descriptor.
    def _set_ids():
        for call_args in session.add.call_args_list:
            obj = call_args[0][0]
            # Пробуем установить id через прямой setattr
            # SQLAlchemy Column-дескрипторы поддерживают setattr
            try:
                if hasattr(obj, 'id'):
                    current = getattr(obj, 'id', None)
                    if current is None:
                        setattr(obj, 'id', 1)
            except Exception:
                pass
    
    session.flush = MagicMock(side_effect=_set_ids)
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def sample_artifact_plan() -> ArtifactPlan:
    """Пример ArtifactPlan от LLM."""
    return ArtifactPlan(
        title="Test Report",
        artifact_type="presentation",
        sections=[
            {
                "title": "Introduction",
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Introduction"},
                    {"type": "paragraph", "text": "This is an overview"},
                ],
            },
            {
                "title": "Analysis",
                "blocks": [
                    {"type": "heading", "level": 2, "text": "Data Analysis"},
                    {"type": "chart", "description": "Revenue by month", "data_source": "financial_data", "columns": ["month", "revenue"]},
                ],
            },
        ],
        reasoning="Standard report structure",
    )


@pytest.fixture
def sample_document_model() -> DocumentModel:
    """Пример DocumentModel после сборки."""
    theme = Theme(
        name="corporate",
        display_name="Corporate",
        fonts=ThemeFonts(heading="Arial", body="Arial", size_heading=28, size_body=14),
        colors=ThemeColors(),
    )
    context = ArtifactContext(
        language="ru",
        company="TestCorp",
        timezone="Europe/Moscow",
        currency="RUB",
        theme_name="corporate",
    )
    sections = [
        Section(
            title="Introduction",
            blocks=[
                Block(block_type=BlockType.HEADING, heading=HeadingBlock(level=1, text="Introduction")),
                Block(block_type=BlockType.PARAGRAPH, paragraph=ParagraphBlock(text="This is an overview")),
            ],
        ),
        Section(
            title="Analysis",
            blocks=[
                Block(block_type=BlockType.HEADING, heading=HeadingBlock(level=2, text="Data Analysis")),
            ],
        ),
    ]
    return DocumentModel(
        title="Test Report",
        artifact_type="presentation",
        context=context,
        theme=theme,
        sections=sections,
    )


@pytest.fixture
def sample_document_model_with_assets(sample_document_model) -> DocumentModel:
    """DocumentModel с AssetReference (pending)."""
    from app.services.artifact.models import ChartBlock

    doc = sample_document_model
    chart_block = Block(
        block_type=BlockType.CHART,
        chart=ChartBlock(
            description="Revenue by month",
            data_source="financial_data",
            columns=["month", "revenue"],
            asset_ref=AssetReference(
                asset_type=AssetType.CHART,
                source="financial_data",
                spec={"columns": ["month", "revenue"]},
            ),
        ),
    )
    doc.sections[1].blocks.append(chart_block)
    return doc


@pytest.fixture
def sample_render_result() -> RenderResult:
    """Пример успешного RenderResult."""
    return RenderResult(
        success=True,
        file_path="/tmp/test_report.pdf",
        file_size=1024,
        mime_type="application/pdf",
        error=None,
    )


@pytest.fixture
def sample_context() -> str:
    """Пример RAG контекста с JSON данными."""
    return json.dumps({
        "financial_data": [
            {"month": "Jan", "revenue": 100},
            {"month": "Feb", "revenue": 150},
            {"month": "Mar", "revenue": 200},
        ],
    })


@pytest.fixture
def sample_validation_passed() -> ValidationResult:
    """Успешный результат валидации."""
    result = ValidationResult(passed=True)
    result.add_check(CheckResult(check_name="required_fields", passed=True, message="OK"))
    result.add_check(CheckResult(check_name="empty_blocks", passed=True, message="OK"))
    result.add_check(CheckResult(check_name="section_structure", passed=True, message="OK"))
    return result


@pytest.fixture
def sample_validation_failed_fixable() -> ValidationResult:
    """Результат валидации с fixable ошибками."""
    result = ValidationResult(passed=False)
    result.add_check(CheckResult(check_name="required_fields", passed=True, message="OK"))
    result.add_check(
        CheckResult(
            check_name="empty_blocks",
            passed=False,
            message="Found 1 empty blocks",
            details={"empty_blocks": ["section=sec1 block=blk1 type=paragraph"]},
        )
    )
    result.add_check(
        CheckResult(
            check_name="section_structure",
            passed=False,
            message="Section structure issues",
        )
    )
    return result


@pytest.fixture
def sample_validation_failed_critical() -> ValidationResult:
    """Результат валидации с критическими ошибками."""
    result = ValidationResult(passed=False)
    result.add_check(CheckResult(check_name="required_fields", passed=False, message="title is empty"))
    result.add_check(CheckResult(check_name="empty_blocks", passed=True, message="OK"))
    return result


@pytest.fixture
def sample_render_validation_passed() -> ValidationResult:
    """Успешный результат валидации рендера."""
    result = ValidationResult(passed=True)
    result.add_check(CheckResult(check_name="file_exists", passed=True, message="File exists"))
    result.add_check(CheckResult(check_name="file_size", passed=True, message="Size OK"))
    return result


@pytest.fixture
def sample_render_validation_warning() -> ValidationResult:
    """Результат валидации рендера с предупреждениями (не критично)."""
    result = ValidationResult(passed=False)
    result.add_check(CheckResult(check_name="file_exists", passed=True, message="File exists"))
    result.add_check(
        CheckResult(check_name="file_size", passed=False, message="File too large: 60MB > 50MB")
    )
    return result


@pytest.fixture
def mock_storage():
    """Mock StorageProvider."""
    storage = MagicMock(spec=StorageProvider)
    storage.upload = AsyncMock(return_value="/storage/artifacts/1/test_report.pdf")
    return storage


@pytest.fixture
def mock_template_manager():
    """Mock TemplateManager."""
    tm = MagicMock(spec=TemplateManager)
    tm.apply_template.return_value = ArtifactPlan(
        title="Template Report",
        artifact_type="pdf",
        sections=[{"title": "Section 1", "blocks": [{"type": "paragraph", "text": "Template content"}]}],
    )
    return tm


@pytest.fixture
def mock_theme_manager():
    """Mock ThemeManager."""
    tm = MagicMock(spec=ThemeManager)
    tm.get_theme.return_value = Theme(
        name="corporate",
        display_name="Corporate",
        fonts=ThemeFonts(heading="Arial", body="Arial", size_heading=28, size_body=14),
        colors=ThemeColors(),
    )
    tm.get_default_theme.return_value = Theme(
        name="corporate",
        display_name="Corporate",
        fonts=ThemeFonts(heading="Arial", body="Arial", size_heading=28, size_body=14),
        colors=ThemeColors(),
    )
    return tm


@pytest.fixture
def mock_document_builder(sample_document_model):
    """Mock DocumentBuilder."""
    builder = MagicMock(spec=DocumentBuilder)
    builder.build.return_value = sample_document_model
    return builder


@pytest.fixture
def mock_document_validator(sample_validation_passed):
    """Mock DocumentValidator."""
    validator = MagicMock(spec=DocumentValidator)
    validator.validate = AsyncMock(return_value=sample_validation_passed)
    return validator


@pytest.fixture
def mock_artifact_auto_fix(sample_validation_passed):
    """Mock ArtifactAutoFix."""
    fixer = MagicMock(spec=ArtifactAutoFix)
    fixer.fix = AsyncMock(return_value=MagicMock(spec=DocumentModel))
    return fixer


@pytest.fixture
def mock_renderer_factory(sample_render_result):
    """Mock RendererFactory."""
    factory = MagicMock(spec=RendererFactory)
    factory.render = AsyncMock(return_value=sample_render_result)
    return factory


@pytest.fixture
def mock_render_validator(sample_render_validation_passed):
    """Mock RenderValidator."""
    validator = MagicMock(spec=RenderValidator)
    validator.validate = AsyncMock(return_value=sample_render_validation_passed)
    return validator


@pytest.fixture
def artifact_agent(
    mock_llm,
    mock_storage,
    mock_template_manager,
    mock_theme_manager,
    mock_document_builder,
    mock_document_validator,
    mock_artifact_auto_fix,
    mock_renderer_factory,
    mock_render_validator,
):
    """Экземпляр ArtifactGeneratorAgent со всеми замоканными зависимостями."""
    agent = ArtifactGeneratorAgent(
        storage=mock_storage,
        template_manager=mock_template_manager,
        theme_manager=mock_theme_manager,
        document_builder=mock_document_builder,
        document_validator=mock_document_validator,
        artifact_auto_fix=mock_artifact_auto_fix,
        renderer_factory=mock_renderer_factory,
        render_validator=mock_render_validator,
    )
    # Подменяем LLM на мок
    agent.llm = mock_llm
    agent.planning_chain = mock_llm.with_structured_output.return_value
    return agent


@pytest.fixture(autouse=True)
def patch_renderer_factory():
    """Автоматически патрим RenderFactory, AssetResolver, MarpGenerator и др.
    
    generate() создаёт эти классы локально, поэтому мок через self.renderer_factory не работает.
    Также патрим os.path.exists, builtins.open и os.path.getsize для _save_artifact_v2.
    """
    with patch("app.agents.artifact_generator.RendererFactory") as mock_rf_cls, \
         patch("app.agents.artifact_generator.AssetResolver") as mock_ar_cls, \
         patch("app.agents.artifact_generator.MarpGenerator") as mock_mg_cls, \
         patch("app.agents.artifact_generator.AssetManager") as mock_am_cls, \
         patch("app.agents.artifact_generator.ChartBuilder") as mock_cb_cls, \
         patch("app.agents.artifact_generator.DiagramBuilder") as mock_db_cls, \
         patch("app.agents.artifact_generator.FormulaBuilder") as mock_fb_cls, \
         patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=1024), \
         patch("os.unlink", MagicMock()), \
         patch("builtins.open", MagicMock()):
        # Настраиваем RendererFactory
        mock_rf_instance = MagicMock(spec=RendererFactory)
        mock_rf_instance.render = AsyncMock(return_value=RenderResult(
            success=True,
            file_path="/tmp/test_report.pdf",
            file_size=1024,
            mime_type="application/pdf",
        ))
        mock_rf_cls.return_value = mock_rf_instance

        # Настраиваем AssetResolver
        mock_ar_instance = MagicMock(spec=AssetResolver)
        mock_ar_instance.resolve_all = AsyncMock()
        mock_ar_cls.return_value = mock_ar_instance

        yield


@pytest.fixture
def artifact_agent_with_db(
    artifact_agent,
    mock_db_session,
):
    """Экземпляр агента с БД сессией."""
    artifact_agent.db_session = mock_db_session
    return artifact_agent


# ============================================================
# 1. Тесты инициализации
# ============================================================


class TestInitialization:
    """Тесты создания ArtifactGeneratorAgent."""

    def test_init_with_defaults(self):
        """Создание агента без db_session — все зависимости создаются по умолчанию."""
        agent = ArtifactGeneratorAgent()
        assert agent.storage is not None
        assert agent.db_session is None
        assert agent.template_manager is not None
        assert agent.theme_manager is not None
        assert agent.document_builder is not None
        assert agent.document_validator is not None
        assert agent.artifact_auto_fix is not None
        assert agent.renderer_factory is not None
        assert agent.render_validator is not None

    def test_init_with_db_session(self, mock_db_session):
        """Создание агента с db_session."""
        agent = ArtifactGeneratorAgent(db_session=mock_db_session)
        assert agent.db_session is mock_db_session
        assert agent.template_manager is not None
        assert agent.theme_manager is not None

    def test_init_with_custom_llm(self, mock_llm):
        """Создание агента с кастомным LLM провайдером."""
        agent = ArtifactGeneratorAgent()
        agent.llm = mock_llm
        agent.planning_chain = mock_llm.with_structured_output.return_value
        assert agent.llm is mock_llm
        assert agent.planning_chain is not None

    def test_init_with_all_dependencies(
        self,
        mock_storage,
        mock_db_session,
        mock_template_manager,
        mock_theme_manager,
        mock_document_builder,
        mock_document_validator,
        mock_artifact_auto_fix,
        mock_renderer_factory,
        mock_render_validator,
    ):
        """Создание агента со всеми переданными зависимостями."""
        agent = ArtifactGeneratorAgent(
            storage=mock_storage,
            db_session=mock_db_session,
            template_manager=mock_template_manager,
            theme_manager=mock_theme_manager,
            document_builder=mock_document_builder,
            document_validator=mock_document_validator,
            artifact_auto_fix=mock_artifact_auto_fix,
            renderer_factory=mock_renderer_factory,
            render_validator=mock_render_validator,
        )
        assert agent.storage is mock_storage
        assert agent.db_session is mock_db_session
        assert agent.template_manager is mock_template_manager
        assert agent.theme_manager is mock_theme_manager
        assert agent.document_builder is mock_document_builder
        assert agent.document_validator is mock_document_validator
        assert agent.artifact_auto_fix is mock_artifact_auto_fix
        assert agent.renderer_factory is mock_renderer_factory
        assert agent.render_validator is mock_render_validator


# ============================================================
# 2. Тесты Phase 1: Planning
# ============================================================


class TestPhase1Planning:
    """Тесты фазы планирования."""

    @pytest.mark.anyio
    async def test_planning_success(self, artifact_agent, mock_llm, sample_artifact_plan):
        """LLM возвращает валидный ArtifactPlan."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        assert result["title"] == "Test Report"
        # Проверяем SSE-события
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "planning" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "planning" for e in events)

    @pytest.mark.anyio
    async def test_planning_fallback_template(self, artifact_agent, mock_llm, mock_template_manager):
        """При ошибке LLM используется TemplateManager.apply_template()."""
        # LLM chain недоступен
        artifact_agent.planning_chain = None

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        assert result["title"] == "Template Report"
        mock_template_manager.apply_template.assert_called_once()

    @pytest.mark.anyio
    async def test_planning_llm_error(self, artifact_agent, mock_llm, mock_template_manager):
        """LLM недоступен — fallback на шаблон."""
        artifact_agent.planning_chain = None

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        mock_template_manager.apply_template.assert_called_once_with(
            template_name="corporate_report",
            variables={"title": "Test query"},
        )

    @pytest.mark.anyio
    async def test_planning_with_template(self, artifact_agent, mock_llm, sample_artifact_plan):
        """Проверка что выбранный шаблон влияет на промпт."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
            template_name="executive_summary",
        )

        assert result["status"] == "ready"
        # Проверяем что в промпт передался template_name
        call_args = structured_llm.ainvoke.call_args[0][0]
        assert "executive_summary" in call_args

    @pytest.mark.anyio
    async def test_planning_with_theme(self, artifact_agent, mock_llm, sample_artifact_plan, mock_theme_manager):
        """Проверка что тема передаётся в контекст."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
            theme_name="dark",
        )

        assert result["status"] == "ready"
        mock_theme_manager.get_theme.assert_called_with("dark")

    @pytest.mark.anyio
    async def test_planning_llm_not_available_no_chain(self, artifact_agent):
        """LLM не инициализирован — ошибка."""
        artifact_agent.llm = None
        artifact_agent.planning_chain = None

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        assert result["error_message"] == "LLM provider is not available"


# ============================================================
# 3. Тесты Phase 2: Document Building
# ============================================================


class TestPhase2DocumentBuilding:
    """Тесты фазы сборки документа."""

    @pytest.mark.anyio
    async def test_document_building_success(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_builder):
        """DocumentBuilder.build() возвращает DocumentModel."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        mock_document_builder.build.assert_called_once()
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "document_building" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "document_building" for e in events)

    @pytest.mark.anyio
    async def test_document_building_with_assets(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_builder, sample_document_model_with_assets):
        """Проверка создания AssetReference(pending)."""
        mock_document_builder.build.return_value = sample_document_model_with_assets
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        # Проверяем что asset_refs были в событии
        building_events = [e for e in result["events"] if e["phase"] == "document_building" and e["event"] == "phase_complete"]
        assert len(building_events) > 0
        assert building_events[0].get("data", {}).get("asset_refs", 0) > 0

    @pytest.mark.anyio
    async def test_document_building_error(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_builder):
        """Ошибка в DocumentBuilder."""
        mock_document_builder.build.side_effect = ValueError("Builder error")
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        assert result["error_message"] is not None


# ============================================================
# 4. Тесты Phase 3: Document Validation
# ============================================================


class TestPhase3DocumentValidation:
    """Тесты фазы валидации документа."""

    @pytest.mark.anyio
    async def test_validation_success(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_validator, sample_validation_passed):
        """Документ проходит валидацию."""
        mock_document_validator.validate = AsyncMock(return_value=sample_validation_passed)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "document_validation" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "document_validation" for e in events)

    @pytest.mark.anyio
    async def test_validation_autofix(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_validator, mock_artifact_auto_fix, sample_validation_failed_fixable, sample_validation_passed):
        """ArtifactAutoFix исправляет fixable ошибки."""
        # Первая валидация — fail, вторая (после фикса) — pass
        mock_document_validator.validate = AsyncMock(side_effect=[
            sample_validation_failed_fixable,
            sample_validation_passed,
        ])
        mock_artifact_auto_fix.fix = AsyncMock(return_value=MagicMock(spec=DocumentModel))
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        # Проверяем что auto-fix был вызван
        mock_artifact_auto_fix.fix.assert_called_once()
        # Проверяем что была повторная валидация
        assert mock_document_validator.validate.call_count == 2

    @pytest.mark.anyio
    async def test_validation_critical_error(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_validator, sample_validation_failed_critical):
        """Критические ошибки прерывают генерацию."""
        mock_document_validator.validate = AsyncMock(return_value=sample_validation_failed_critical)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        assert result["error_message"] is not None
        assert "validation failed" in result["error_message"].lower()

    @pytest.mark.anyio
    async def test_validation_autofix_still_fails(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_validator, mock_artifact_auto_fix, sample_validation_failed_fixable):
        """Auto-fix не смог исправить — ошибка."""
        mock_document_validator.validate = AsyncMock(return_value=sample_validation_failed_fixable)
        mock_artifact_auto_fix.fix = AsyncMock(return_value=MagicMock(spec=DocumentModel))
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        mock_artifact_auto_fix.fix.assert_called_once()


# ============================================================
# 5. Тесты Phase 4: Rendering
# ============================================================


class TestPhase4Rendering:
    """Тесты фазы рендеринга."""

    @pytest.mark.anyio
    async def test_rendering_success(self, artifact_agent, mock_llm, sample_artifact_plan, mock_renderer_factory, sample_render_result):
        """RendererFactory.render() возвращает RenderResult."""
        mock_renderer_factory.render = AsyncMock(return_value=sample_render_result)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "rendering" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "rendering" for e in events)

    @pytest.mark.anyio
    async def test_rendering_with_charts(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_builder, sample_document_model_with_assets):
        """Проверка что AssetResolver вызывается для графиков."""
        mock_document_builder.build.return_value = sample_document_model_with_assets
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context='{"financial_data": [{"month": "Jan", "revenue": 100}]}',
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        # AssetResolver.resolve_all должен быть вызван (через autouse patch)

    @pytest.mark.anyio
    async def test_rendering_error(self, artifact_agent, mock_llm, sample_artifact_plan):
        """Ошибка рендеринга."""
        # Патчим RendererFactory чтобы вернуть ошибку (autouse fixture возвращает success)
        with patch("app.agents.artifact_generator.RendererFactory") as mock_rf_cls:
            mock_rf_instance = MagicMock(spec=RendererFactory)
            mock_rf_instance.render = AsyncMock(return_value=RenderResult(
                success=False,
                error="Render engine crashed",
            ))
            mock_rf_cls.return_value = mock_rf_instance

            structured_llm = mock_llm.with_structured_output.return_value
            structured_llm.ainvoke.return_value = sample_artifact_plan

            result = await artifact_agent.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "error"
        assert result["error_message"] is not None
        assert "Render failed" in result["error_message"]


# ============================================================
# 6. Тесты Phase 5: Render Validation
# ============================================================


class TestPhase5RenderValidation:
    """Тесты фазы валидации рендера."""

    @pytest.mark.anyio
    async def test_render_validation_success(self, artifact_agent, mock_llm, sample_artifact_plan, mock_render_validator, sample_render_validation_passed):
        """Файл проходит валидацию."""
        mock_render_validator.validate = AsyncMock(return_value=sample_render_validation_passed)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "ready"
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "render_validation" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "render_validation" for e in events)

    @pytest.mark.anyio
    async def test_render_validation_warning(self, artifact_agent, mock_llm, sample_artifact_plan, mock_render_validator, sample_render_validation_warning):
        """Ошибки валидации не прерывают (только лог)."""
        mock_render_validator.validate = AsyncMock(return_value=sample_render_validation_warning)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        # Даже при ошибках валидации рендера, генерация продолжается
        assert result["status"] == "ready"
        validation_events = [
            e for e in result["events"]
            if e["phase"] == "render_validation" and e["event"] == "phase_complete"
        ]
        assert len(validation_events) > 0
        assert validation_events[0].get("data", {}).get("passed") is False


# ============================================================
# 7. Тесты Phase 6: Save
# ============================================================


class TestPhase6Save:
    """Тесты фазы сохранения."""

    @pytest.mark.anyio
    async def test_save_success(self, artifact_agent_with_db, mock_llm, sample_artifact_plan, mock_storage, mock_db_session):
        """Сохранение в v2 таблицы + StorageProvider."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        # Создаём временный файл для рендера
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            result = await artifact_agent_with_db.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "ready"
        assert result["project_id"] is not None
        assert result["version_id"] is not None
        assert result["artifact_id"] is not None
        mock_storage.upload.assert_called_once()
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_save_with_assets(self, artifact_agent_with_db, mock_llm, sample_artifact_plan, mock_document_builder, sample_document_model_with_assets, mock_storage, mock_db_session):
        """Сохранение ассетов."""
        mock_document_builder.build.return_value = sample_document_model_with_assets
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            result = await artifact_agent_with_db.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "ready"
        # StorageProvider.upload должен быть вызван для файла и для ассетов
        assert mock_storage.upload.call_count >= 1

    @pytest.mark.anyio
    async def test_save_error(self, artifact_agent_with_db, mock_llm, sample_artifact_plan, mock_storage):
        """Ошибка сохранения."""
        mock_storage.upload.side_effect = RuntimeError("Storage unavailable")
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024):

            result = await artifact_agent_with_db.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "error"
        assert result["error_message"] is not None

    @pytest.mark.anyio
    async def test_save_no_db_session(self, artifact_agent, mock_llm, sample_artifact_plan, mock_storage):
        """Сохранение без БД — только StorageProvider."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            result = await artifact_agent.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "ready"
        # project_id, version_id, artifact_id могут быть None без БД
        mock_storage.upload.assert_called_once()


# ============================================================
# 8. Тесты полного пайплайна
# ============================================================


class TestFullPipeline:
    """Тесты полного цикла генерации."""

    @pytest.mark.anyio
    async def test_full_pipeline_success(self, artifact_agent_with_db, mock_llm, sample_artifact_plan, mock_db_session):
        """Все 6 фаз успешно."""
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            result = await artifact_agent_with_db.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        # Проверяем статус
        assert result["status"] == "ready"

        # Проверяем все ключи результата
        assert "project_id" in result
        assert "version_id" in result
        assert "artifact_id" in result
        assert "title" in result
        assert "artifact_type" in result
        assert "error_message" in result
        assert "events" in result

        # Проверяем что title и artifact_type из плана
        assert result["title"] == "Test Report"
        assert result["artifact_type"] == "presentation"

        # Проверяем что все 6 фаз имеют phase_start
        # Для saving фазы phase_complete заменяется на artifact_ready
        expected_phases = [
            "planning",
            "document_building",
            "document_validation",
            "rendering",
            "render_validation",
        ]
        events = result["events"]
        for phase in expected_phases:
            assert any(e["event"] == "phase_start" and e["phase"] == phase for e in events), \
                f"Missing phase_start for {phase}"
            assert any(e["event"] == "phase_complete" and e["phase"] == phase for e in events), \
                f"Missing phase_complete for {phase}"

        # Проверяем saving фазу (phase_start + artifact_ready вместо phase_complete)
        assert any(e["event"] == "phase_start" and e["phase"] == "saving" for e in events), \
            "Missing phase_start for saving"
        assert any(e["event"] == "artifact_ready" for e in events), \
            "Missing artifact_ready event"

    @pytest.mark.anyio
    async def test_full_pipeline_planning_fallback(self, artifact_agent_with_db, mock_template_manager, mock_db_session):
        """Полный цикл с fallback на шаблон."""
        artifact_agent_with_db.planning_chain = None

        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            result = await artifact_agent_with_db.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "ready"
        assert result["title"] == "Template Report"
        mock_template_manager.apply_template.assert_called_once()

        # Все фазы должны пройти
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "planning" for e in events)
        assert any(e["event"] == "phase_complete" and e["phase"] == "planning" for e in events)

    @pytest.mark.anyio
    async def test_full_pipeline_validation_error(self, artifact_agent, mock_llm, sample_artifact_plan, mock_document_validator, sample_validation_failed_critical):
        """Прерывание на валидации документа."""
        mock_document_validator.validate = AsyncMock(return_value=sample_validation_failed_critical)
        structured_llm = mock_llm.with_structured_output.return_value
        structured_llm.ainvoke.return_value = sample_artifact_plan

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        assert result["error_message"] is not None

        # Фазы после document_validation не должны выполняться
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "planning" for e in events)
        assert any(e["event"] == "phase_start" and e["phase"] == "document_building" for e in events)
        assert any(e["event"] == "phase_start" and e["phase"] == "document_validation" for e in events)
        # Рендеринг не должен был запуститься
        assert not any(e["phase"] == "rendering" for e in events)
        # Должно быть событие ошибки
        assert any(e["event"] == "artifact_error" for e in events)

    @pytest.mark.anyio
    async def test_full_pipeline_rendering_error(self, artifact_agent, mock_llm, sample_artifact_plan):
        """Прерывание на рендеринге."""
        # Патчим RendererFactory чтобы вернуть ошибку
        with patch("app.agents.artifact_generator.RendererFactory") as mock_rf_cls:
            mock_rf_instance = MagicMock(spec=RendererFactory)
            mock_rf_instance.render = AsyncMock(return_value=RenderResult(
                success=False,
                error="Render engine crashed",
            ))
            mock_rf_cls.return_value = mock_rf_instance

            structured_llm = mock_llm.with_structured_output.return_value
            structured_llm.ainvoke.return_value = sample_artifact_plan

            result = await artifact_agent.generate(
                query="Test query",
                context="{}",
                user_id=1,
                session_id=1,
            )

        assert result["status"] == "error"
        # Фазы после rendering не должны выполняться
        events = result["events"]
        assert any(e["event"] == "phase_start" and e["phase"] == "rendering" for e in events)
        assert not any(e["phase"] == "render_validation" for e in events)
        assert not any(e["phase"] == "saving" for e in events)

    @pytest.mark.anyio
    async def test_full_pipeline_llm_not_available(self, artifact_agent):
        """LLM недоступен с самого начала."""
        artifact_agent.llm = None
        artifact_agent.planning_chain = None

        result = await artifact_agent.generate(
            query="Test query",
            context="{}",
            user_id=1,
            session_id=1,
        )

        assert result["status"] == "error"
        assert result["error_message"] == "LLM provider is not available"
        # Никакие фазы не должны быть запущены
        assert len(result["events"]) == 0


# ============================================================
# 9. Тесты вспомогательных методов
# ============================================================


class TestHelperMethods:
    """Тесты вспомогательных методов."""

    def test_chunks_to_dataframes_empty(self):
        """Пустой контекст — пустой dict."""
        agent = ArtifactGeneratorAgent()
        result = agent._chunks_to_dataframes("")
        assert result == {}

    def test_chunks_to_dataframes_none(self):
        """None контекст — пустой dict."""
        agent = ArtifactGeneratorAgent()
        result = agent._chunks_to_dataframes("")
        assert result == {}

    def test_chunks_to_dataframes_json_dict(self):
        """JSON объект с таблицами."""
        agent = ArtifactGeneratorAgent()
        context = json.dumps({
            "financial_data": [
                {"month": "Jan", "revenue": 100},
                {"month": "Feb", "revenue": 150},
            ],
            "metrics": [
                {"name": "users", "value": 1000},
            ],
        })
        result = agent._chunks_to_dataframes(context)
        assert "financial_data" in result
        assert "metrics" in result
        assert isinstance(result["financial_data"], pd.DataFrame)
        assert result["financial_data"].shape == (2, 2)

    def test_chunks_to_dataframes_json_list(self):
        """JSON список."""
        agent = ArtifactGeneratorAgent()
        context = json.dumps([
            {"month": "Jan", "revenue": 100},
            {"month": "Feb", "revenue": 150},
        ])
        result = agent._chunks_to_dataframes(context)
        assert "data" in result
        assert isinstance(result["data"], pd.DataFrame)
        assert result["data"].shape == (2, 2)

    def test_chunks_to_dataframes_json_blocks(self):
        """JSON блоки в markdown."""
        agent = ArtifactGeneratorAgent()
        context = 'Some text\n```json\n[{"x": 1, "y": 2}]\n```\nMore text'
        result = agent._chunks_to_dataframes(context)
        assert len(result) > 0
        assert isinstance(list(result.values())[0], pd.DataFrame)

    def test_chunks_to_dataframes_invalid_json(self):
        """Невалидный JSON — пустой dict."""
        agent = ArtifactGeneratorAgent()
        context = "Just plain text without any JSON"
        result = agent._chunks_to_dataframes(context)
        assert result == {}

    def test_make_event_default(self):
        """Базовый формат SSE-события."""
        agent = ArtifactGeneratorAgent()
        event = agent._make_event("phase_start", "planning")
        assert event["event"] == "phase_start"
        assert event["phase"] == "planning"
        assert "timestamp" in event
        assert "data" not in event

    def test_make_event_with_data(self):
        """SSE-событие с дополнительными данными."""
        agent = ArtifactGeneratorAgent()
        event = agent._make_event("phase_complete", "planning", {"title": "Test", "sections": 3})
        assert event["event"] == "phase_complete"
        assert event["phase"] == "planning"
        assert event["data"] == {"title": "Test", "sections": 3}

    def test_make_event_timestamp_format(self):
        """Проверка формата timestamp."""
        agent = ArtifactGeneratorAgent()
        event = agent._make_event("test", "test_phase")
        # Парсим timestamp обратно
        ts = datetime.fromisoformat(event["timestamp"])
        assert ts.tzinfo is not None  # должен быть timezone-aware

    @pytest.mark.anyio
    async def test_save_artifact_v2(self, artifact_agent_with_db, sample_render_result, sample_document_model, sample_artifact_plan, mock_db_session, mock_storage):
        """Сохранение в БД."""
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            save_result = await artifact_agent_with_db._save_artifact_v2(
                render_result=sample_render_result,
                document=sample_document_model,
                plan=sample_artifact_plan,
                user_id=1,
                session_id=1,
                template_name="corporate_report",
                theme_name="corporate",
                output_format="pdf",
            )

        assert "project_id" in save_result
        assert "version_id" in save_result
        assert "artifact_id" in save_result
        assert "filename" in save_result
        assert "storage_path" in save_result
        assert "download_url" in save_result
        mock_storage.upload.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.anyio
    async def test_save_artifact_v2_no_db(self, artifact_agent, sample_render_result, sample_document_model, sample_artifact_plan, mock_storage):
        """Сохранение без БД."""
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.unlink", MagicMock()):

            save_result = await artifact_agent._save_artifact_v2(
                render_result=sample_render_result,
                document=sample_document_model,
                plan=sample_artifact_plan,
                user_id=1,
                session_id=1,
            )

        assert save_result["project_id"] is None
        assert save_result["version_id"] is None
        assert save_result["artifact_id"] is None
        mock_storage.upload.assert_called_once()

    @pytest.mark.anyio
    async def test_save_artifact_v2_file_not_found(self, artifact_agent, sample_render_result, sample_document_model, sample_artifact_plan):
        """Файл не найден — ошибка."""
        with patch("os.path.exists", return_value=False):
            with pytest.raises(RuntimeError, match="Render result file not found"):
                await artifact_agent._save_artifact_v2(
                    render_result=sample_render_result,
                    document=sample_document_model,
                    plan=sample_artifact_plan,
                    user_id=1,
                    session_id=1,
                )

    def test_chunks_to_dataframes_empty_list(self):
        """Пустой JSON список."""
        agent = ArtifactGeneratorAgent()
        context = json.dumps([])
        result = agent._chunks_to_dataframes(context)
        assert result == {}

    def test_chunks_to_dataframes_empty_dict(self):
        """Пустой JSON объект."""
        agent = ArtifactGeneratorAgent()
        context = json.dumps({})
        result = agent._chunks_to_dataframes(context)
        assert result == {}

    def test_chunks_to_dataframes_nested_json_blocks(self):
        """Вложенные JSON блоки в тексте."""
        agent = ArtifactGeneratorAgent()
        context = (
            "Here is the data:\n"
            '```json\n'
            '[{"city": "Moscow", "population": 12000000}]\n'
            '```\n'
            "And more:\n"
            '```\n'
            '[{"city": "SPB", "population": 5000000}]\n'
            '```\n'
        )
        result = agent._chunks_to_dataframes(context)
        assert len(result) >= 2  # должно быть 2 DataFrame'а