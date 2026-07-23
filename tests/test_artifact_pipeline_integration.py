"""Integration-тесты для полного пайплайна генерации артефактов v2.

Секции:
1. API → Оркестратор → Агент (полный E2E с mock'ами)
2. API endpoints (CRUD для v2: проекты, версии, ассеты, шаблоны, темы)
3. Полный pipeline (агент → сервисы → БД)
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Импорт приложения — должен быть первым, чтобы dependency_overrides работали
from main import fastapi_app as app
from app.core.config import Base
from app.core.security import create_access_token
from app.api.deps import get_db, get_current_user, get_current_user_groups
from app.models.user import User, UserGroup, user_group_membership
from app.models.artifact_v2 import (
    ArtifactProject,
    ArtifactVersion,
    ArtifactAsset,
    ArtifactTemplate,
    Theme,
)
from app.services.artifact.models import (
    ArtifactContext,
    ArtifactPlan,
    ArtifactStatus,
    AssetReference,
    AssetType,
    Block,
    BlockType,
    DocumentModel,
    HeadingBlock,
    ParagraphBlock,
    RenderResult,
    Section,
    Theme as ThemeModel,
    ThemeColors,
    ThemeFonts,
    ValidationResult,
    CheckResult,
)
from app.services.artifact.document_builder import DocumentBuilder
from app.services.artifact.renderer_factory import RendererFactory
from app.services.artifact.asset_resolver import AssetResolver
from app.services.artifact.asset_manager import AssetManager
from app.services.artifact.template_manager import TemplateManager
from app.services.artifact.theme_manager import ThemeManager
from app.services.artifact.validator import DocumentValidator, ArtifactAutoFix, RenderValidator
from app.services.artifact.chart_builder import ChartBuilder
from app.services.artifact.diagram_builder import DiagramBuilder
from app.services.artifact.formula_builder import FormulaBuilder
from app.services.artifact.marp_generator import MarpGenerator
from app.services.artifact.marp_renderer import MarpRenderer
from app.services.storage import MockStorageProvider, StorageProvider
from app.agents.orchestrator import AgentOrchestrator
from app.agents.artifact_generator import ArtifactGeneratorAgent

# Регистрируем anyio маркер для pytest
pytest_plugins = ("anyio",)


# ============================================================
# Helper: создание in-memory SQLite БД и переопределение зависимостей
# ============================================================


# Единый mock-пользователь для всех тестов
_MOCK_USER = User(
    id=1,
    email="test@example.com",
    username="testuser",
    hashed_password="fakehash",
    is_active=True,
)


def _create_test_db() -> tuple[Engine, Session]:
    """Создать in-memory SQLite БД со всеми таблицами.

    Использует shared in-memory database (cache=shared) чтобы
    create_all и последующие запросы использовали одну БД.

    Returns:
        (engine, session) кортеж.
    """
    engine = create_engine(
        "sqlite:///file:test_db?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    return engine, session


def _override_deps(session: Session) -> None:
    """Переопределить зависимости FastAPI для тестов."""
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield session
        finally:
            pass

    async def override_get_current_user() -> User:
        return _MOCK_USER

    async def override_get_current_user_groups() -> list[int]:
        return []

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_user_groups] = override_get_current_user_groups


def _cleanup_deps() -> None:
    """Очистить переопределения зависимостей."""
    app.dependency_overrides.clear()


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Создаёт in-memory SQLite БД для каждого теста.

    Переопределяет get_db, get_current_user и get_current_user_groups.
    """
    engine, session = _create_test_db()
    _override_deps(session)
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    _cleanup_deps()


@pytest.fixture
def test_client() -> TestClient:
    """Создать TestClient для FastAPI приложения."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Создаёт JWT-токен для тестового пользователя."""
    token = create_access_token(data={"sub": "1"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_project(db_session: Session) -> ArtifactProject:
    """Создать тестовый проект в БД."""
    project = ArtifactProject(
        user_id=1,
        session_id=0,
        title="Test Project",
        template_name="corporate_report",
        current_version=1,
        context={"theme_name": "corporate", "output_format": "pdf"},
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture
def sample_version(
    db_session: Session,
    sample_project: ArtifactProject,
) -> ArtifactVersion:
    """Создать тестовую версию в БД."""
    version = ArtifactVersion(
        project_id=sample_project.id,
        version_number=1,
        status=ArtifactStatus.READY,
        document_model={
            "title": "Test Doc",
            "artifact_type": "pdf",
            "sections": [],
            "dependency_graph": {"edges": []},
        },
        dependency_graph={"edges": []},
        storage_path=os.path.join(tempfile.gettempdir(), "test_artifact.pdf"),
        file_size=1024,
        artifact_type="pdf",
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture
def sample_assets(
    db_session: Session,
    sample_version: ArtifactVersion,
) -> list[ArtifactAsset]:
    """Создать тестовые ассеты в БД."""
    assets = [
        ArtifactAsset(
            asset_id="asset-001",
            version_id=sample_version.id,
            asset_type=AssetType.CHART,
            name="Test Chart",
            mime_type="image/png",
            storage_path="/tmp/test_chart.png",
            asset_metadata={"description": "Test chart"},
            size_bytes=2048,
        ),
        ArtifactAsset(
            asset_id="asset-002",
            version_id=sample_version.id,
            asset_type=AssetType.DIAGRAM,
            name="Test Diagram",
            mime_type="image/svg+xml",
            storage_path="/tmp/test_diagram.svg",
            asset_metadata={"engine": "mermaid"},
            size_bytes=1024,
        ),
    ]
    for asset in assets:
        db_session.add(asset)
    db_session.commit()
    for asset in assets:
        db_session.refresh(asset)
    return assets


@pytest.fixture
def sample_template(db_session: Session) -> ArtifactTemplate:
    """Создать системный шаблон в БД."""
    template = ArtifactTemplate(
        name="quarterly_report",
        display_name="Quarterly Report",
        description="A quarterly business report template",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "period": {"type": "string"},
            },
        },
        default_blocks=[
            {"type": "heading", "level": 1, "text": "Quarterly Report"},
            {"type": "paragraph", "text": "Executive summary"},
        ],
        is_system=True,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def sample_theme(db_session: Session) -> Theme:
    """Создать системную тему в БД."""
    theme = Theme(
        name="dark",
        display_name="Dark Theme",
        is_system=True,
        config={
            "colors": {
                "primary": "#1a1a2e",
                "secondary": "#16213e",
                "background": "#0f0f23",
                "text": "#e0e0e0",
            },
            "fonts": {
                "heading": "Arial",
                "body": "Arial",
            },
        },
    )
    db_session.add(theme)
    db_session.commit()
    db_session.refresh(theme)
    return theme


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM провайдера с with_structured_output."""
    llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock()
    llm.with_structured_output.return_value = structured_llm
    return llm


@pytest.fixture
def sample_artifact_plan() -> ArtifactPlan:
    """ArtifactPlan для тестов."""
    return ArtifactPlan(
        title="Test Report",
        artifact_type="pdf",
        sections=[
            {
                "title": "Introduction",
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Introduction"},
                    {"type": "paragraph", "text": "This is a test report."},
                ],
            },
            {
                "title": "Data",
                "blocks": [
                    {"type": "heading", "level": 2, "text": "Sales Data"},
                    {
                        "type": "chart",
                        "description": "Sales by month",
                        "data_source": "sales_data",
                        "columns": ["month", "revenue"],
                    },
                ],
            },
        ],
        reasoning="Test plan for integration tests",
    )


@pytest.fixture
def sample_document_model() -> DocumentModel:
    """DocumentModel для тестов."""
    return DocumentModel(
        title="Test Report",
        artifact_type="pdf",
        context=ArtifactContext(language="ru", company="TestCorp"),
        theme=ThemeModel(
            name="corporate",
            display_name="Corporate",
            fonts=ThemeFonts(heading="Arial", body="Arial"),
            colors=ThemeColors(),
        ),
        sections=[
            Section(
                id="sec-1",
                title="Introduction",
                blocks=[
                    Block(
                        id="block-1",
                        block_type=BlockType.HEADING,
                        heading=HeadingBlock(level=1, text="Introduction"),
                    ),
                    Block(
                        id="block-2",
                        block_type=BlockType.PARAGRAPH,
                        paragraph=ParagraphBlock(text="This is a test report."),
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def sample_render_result() -> RenderResult:
    """RenderResult для тестов."""
    return RenderResult(
        success=True,
        file_path=os.path.join(tempfile.gettempdir(), "test_render.pdf"),
        file_size=4096,
        mime_type="application/pdf",
    )


@pytest.fixture
def temp_output_file() -> Generator[str, None, None]:
    """Создать временный файл для тестов рендеринга."""
    tmp = os.path.join(tempfile.gettempdir(), f"test_artifact_{datetime.now().timestamp()}.pdf")
    with open(tmp, "wb") as f:
        f.write(b"%PDF-1.4 test content\n")
    yield tmp
    if os.path.exists(tmp):
        os.unlink(tmp)


# ============================================================
# 1. API → Оркестратор → Агент (полный E2E с mock'ами)
# ============================================================


class TestApiOrchestratorAgentE2E:
    """Тесты проверяют что все слои вызываются в правильном порядке с правильными параметрами."""

    @patch("app.api.v1.endpoints.chat.get_orchestrator")
    def test_chat_api_triggers_artifact_generation(
        self,
        mock_get_orch: MagicMock,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """POST /api/v1/chat/chat → оркестратор вызван с query, user_id, user_groups.

        Проверка: ответ содержит route='generate' и content с результатом.
        """
        # Arrange: создаём ChatSession в БД (FK constraint)
        from app.models.chat import ChatSession
        chat_session = ChatSession(user_id=1, title="Test Session")
        db_session.add(chat_session)
        db_session.commit()
        db_session.refresh(chat_session)

        mock_orchestrator = MagicMock()
        mock_orchestrator.run = AsyncMock(return_value={
            "query": "Сделай презентацию по продажам",
            "user_id": 1,
            "user_groups": [],
            "route": "generate",
            "artifact_result": {
                "status": "ready",
                "title": "Sales Presentation",
                "artifact_type": "pptx",
                "project_id": 1,
                "version_id": 1,
                "artifact_id": 1,
            },
            "final_answer": (
                "✅ **Артефакт сгенерирован!**\n\n"
                "**Sales Presentation** (PPTX)\n\n"
                "📥 **Скачать:** [ссылка](/api/v1/artifacts/download/1/1)\n"
                "🆔 Проект: `1`\n"
                "🆔 Версия: `1`\n"
                "🆔 Артефакт: `1`\n"
            ),
            "citations": [],
            "error": None,
        })
        mock_get_orch.return_value = mock_orchestrator

        # Act — URL: /api/v1/chat/chat (router prefix /chat + endpoint /chat)
        # Передаём session_id созданной сессии, чтобы chat_sync не создавал новую
        response = test_client.post(
            "/api/v1/chat/chat",
            headers=auth_headers,
            json={
                "message": "Сделай презентацию по продажам",
                "session_id": chat_session.id,
            },
        )

        # Assert
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        data = response.json()
        # chat_sync возвращает: session_id, message_id, content, citations, route, error
        assert data["route"] == "generate"
        assert "Артефакт сгенерирован" in data["content"]

        # Проверяем что оркестратор вызван с правильными параметрами
        mock_orchestrator.run.assert_called_once()
        call_kwargs = mock_orchestrator.run.call_args[1]
        assert call_kwargs["query"] == "Сделай презентацию по продажам"
        assert call_kwargs["user_id"] == 1
        assert isinstance(call_kwargs["user_groups"], list)

    def test_orchestrator_detects_template_from_query(self):
        """AgentOrchestrator._detect_template("Сделай квартальный отчёт") → "quarterly_report"."""
        orchestrator = AgentOrchestrator()
        template_name = orchestrator._detect_template("Сделай квартальный отчёт")
        assert template_name == "quarterly_report"

    def test_orchestrator_detects_format_from_query(self):
        """AgentOrchestrator._detect_format("Сделай презентацию в pptx") → "pptx"."""
        orchestrator = AgentOrchestrator()
        output_format = orchestrator._detect_format("Сделай презентацию в pptx")
        assert output_format == "pptx"

    def test_orchestrator_default_template_and_format(self):
        """AgentOrchestrator defaults: template=corporate_report, format=pdf."""
        orchestrator = AgentOrchestrator()
        template_name = orchestrator._detect_template("Просто отчёт")
        output_format = orchestrator._detect_format("Просто отчёт")
        assert template_name == "corporate_report"
        assert output_format == "pdf"

    @pytest.mark.anyio
    async def test_orchestrator_handles_artifact_error(self):
        """AgentOrchestrator._finalize() при ошибке генерации."""
        orchestrator = AgentOrchestrator()
        state: dict[str, Any] = {
            "query": "Сделай отчёт",
            "user_id": 1,
            "user_groups": [],
            "route": "generate",
            "route_decision": None,
            "search_result": None,
            "summary_result": None,
            "analytics_result": None,
            "artifact_result": {
                "status": "error",
                "error_message": "LLM failed",
                "error": "LLM failed",
            },
            "final_answer": None,
            "citations": [],
            "error": "LLM failed",
            "template_name": "corporate_report",
            "output_format": "pdf",
        }
        result = await orchestrator._finalize(state)  # type: ignore[arg-type]
        assert result["error"] is not None
        assert "LLM failed" in result["error"]


# ============================================================
# 2. API endpoints (CRUD для v2)
# ============================================================


class TestArtifactProjectsAPI:
    """Тесты CRUD для проектов артефактов."""

    def test_list_projects_empty(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """GET /api/v1/artifact-projects/ → 200, пустой список."""
        response = test_client.get("/api/v1/artifact-projects/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["projects"] == []
        assert data["total"] == 0

    def test_create_and_get_project(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """Создать проект через БД, получить через API."""
        project = ArtifactProject(
            user_id=1,
            session_id=0,
            title="Integration Test Project",
            template_name="corporate_report",
            current_version=1,
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        response = test_client.get(
            f"/api/v1/artifact-projects/{project.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Integration Test Project"
        assert data["user_id"] == 1
        assert data["template_name"] == "corporate_report"

    def test_get_project_versions(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_project: ArtifactProject,
        sample_version: ArtifactVersion,
    ):
        """GET /api/v1/artifact-projects/{project_id}/versions → 200."""
        response = test_client.get(
            f"/api/v1/artifact-projects/{sample_project.id}/versions",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["version_number"] == 1
        assert data[0]["artifact_type"] == "pdf"

    def test_get_version_detail(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_project: ArtifactProject,
        sample_version: ArtifactVersion,
    ):
        """GET /api/v1/artifact-projects/{project_id}/versions/{version_id} → 200."""
        response = test_client.get(
            f"/api/v1/artifact-projects/{sample_project.id}/versions/{sample_version.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "document_model" in data
        assert "dependency_graph" in data
        assert data["document_model"]["title"] == "Test Doc"

    def test_get_version_assets(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_project: ArtifactProject,
        sample_version: ArtifactVersion,
        sample_assets: list[ArtifactAsset],
    ):
        """GET /api/v1/artifact-projects/{project_id}/versions/{version_id}/assets → 200."""
        response = test_client.get(
            f"/api/v1/artifact-projects/{sample_project.id}/versions/{sample_version.id}/assets",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["asset_type"] in ("chart", "diagram")

    def test_download_version_file(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_project: ArtifactProject,
        sample_version: ArtifactVersion,
        db_session: Session,
    ):
        """GET /api/v1/artifact-projects/.../download → 200."""
        tmp_file = os.path.join(tempfile.gettempdir(), "test_artifact.pdf")
        with open(tmp_file, "wb") as f:
            f.write(b"%PDF-1.4 test content\n")

        db_session.execute(
            text("UPDATE artifact_versions SET storage_path = :path WHERE id = :id"),
            {"path": tmp_file, "id": sample_version.id},
        )
        db_session.commit()
        db_session.refresh(sample_version)

        response = test_client.get(
            f"/api/v1/artifact-projects/{sample_project.id}/versions/{sample_version.id}/download",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

    def test_delete_project(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_project: ArtifactProject,
    ):
        """DELETE /api/v1/artifact-projects/{project_id} → 204, затем GET → 404."""
        response = test_client.delete(
            f"/api/v1/artifact-projects/{sample_project.id}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        response = test_client.get(
            f"/api/v1/artifact-projects/{sample_project.id}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_foreign_project_returns_404(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """Попытка получить чужой проект → 404."""
        other_project = ArtifactProject(
            user_id=999,
            session_id=0,
            title="Foreign Project",
            template_name="corporate_report",
            current_version=1,
        )
        db_session.add(other_project)
        db_session.commit()
        db_session.refresh(other_project)

        response = test_client.get(
            f"/api/v1/artifact-projects/{other_project.id}",
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestArtifactTemplatesAPI:
    """Тесты CRUD для шаблонов артефактов."""

    def test_list_templates(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """GET /api/v1/artifact-templates/ → 200, содержит системные шаблоны (≥7)."""
        system_templates = [
            ArtifactTemplate(
                name=f"template_{i}",
                display_name=f"Template {i}",
                description=f"System template {i}",
                schema={"type": "object"},
                default_blocks=[],
                is_system=True,
            )
            for i in range(7)
        ]
        for t in system_templates:
            db_session.add(t)
        db_session.commit()

        response = test_client.get("/api/v1/artifact-templates/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 7

    def test_get_template_detail(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_template: ArtifactTemplate,
    ):
        """GET /api/v1/artifact-templates/{template_id} → 200."""
        response = test_client.get(
            f"/api/v1/artifact-templates/{sample_template.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "schema" in data
        assert "default_blocks" in data
        assert data["is_system"] is True
        assert data["name"] == "quarterly_report"

    def test_create_custom_template(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """POST /api/v1/artifact-templates/ с валидными данными → 201."""
        template_data = {
            "name": "my_custom_template",
            "display_name": "My Custom Template",
            "description": "A custom template for testing",
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                },
            },
            "default_blocks": [
                {"type": "heading", "level": 1, "text": "Custom Report"},
            ],
        }
        response = test_client.post(
            "/api/v1/artifact-templates/",
            headers=auth_headers,
            json=template_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my_custom_template"
        assert data["is_system"] is False
        assert data["display_name"] == "My Custom Template"

    def test_delete_system_template_returns_403(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        sample_template: ArtifactTemplate,
    ):
        """DELETE /api/v1/artifact-templates/{system_template_id} → 403."""
        response = test_client.delete(
            f"/api/v1/artifact-templates/{sample_template.id}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestArtifactThemesAPI:
    """Тесты CRUD для тем оформления."""

    def test_list_themes(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """GET /api/v1/artifact-themes/ → 200, содержит системные темы (≥3)."""
        system_themes = [
            Theme(
                name=f"theme_{i}",
                display_name=f"Theme {i}",
                is_system=True,
                config={"colors": {"primary": "#000"}, "fonts": {"heading": "Arial"}},
            )
            for i in range(3)
        ]
        for t in system_themes:
            db_session.add(t)
        db_session.commit()

        response = test_client.get("/api/v1/artifact-themes/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3

    def test_create_custom_theme(
        self,
        test_client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
    ):
        """POST /api/v1/artifact-themes/ с валидными данными → 201."""
        theme_data = {
            "name": "my_custom_theme",
            "display_name": "My Custom Theme",
            "config": {
                "colors": {
                    "primary": "#ff0000",
                    "secondary": "#00ff00",
                    "background": "#ffffff",
                    "text": "#000000",
                },
                "fonts": {
                    "heading": "Times New Roman",
                    "body": "Times New Roman",
                },
            },
        }
        response = test_client.post(
            "/api/v1/artifact-themes/",
            headers=auth_headers,
            json=theme_data,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my_custom_theme"
        assert data["is_system"] is False
        assert data["display_name"] == "My Custom Theme"


# ============================================================
# 3. Полный pipeline (агент → сервисы → БД)
# ============================================================


class TestFullPipeline:
    """Тесты проверяют что все v2 сервисы работают вместе."""

    def test_agent_to_document_builder_integration(self):
        """DocumentBuilder.build() с реальным планом."""
        plan = ArtifactPlan(
            title="Integration Test Report",
            artifact_type="pdf",
            sections=[
                {
                    "title": "Executive Summary",
                    "blocks": [
                        {"type": "heading", "level": 1, "text": "Executive Summary"},
                        {"type": "paragraph", "text": "This is a summary."},
                    ],
                },
                {
                    "title": "Charts",
                    "blocks": [
                        {
                            "type": "chart",
                            "description": "Revenue by quarter",
                            "data_source": "financial_data",
                            "columns": ["quarter", "revenue"],
                        },
                    ],
                },
            ],
            reasoning="Test plan",
        )

        builder = DocumentBuilder()
        document = builder.build(
            plan=plan,
            context=ArtifactContext(language="ru", company="TestCorp"),
            theme=ThemeModel(
                name="corporate",
                display_name="Corporate",
                fonts=ThemeFonts(heading="Arial", body="Arial"),
                colors=ThemeColors(),
            ),
        )

        assert isinstance(document, DocumentModel)
        assert document.title == "Integration Test Report"
        assert len(document.sections) == 2
        assert document.sections[0].title == "Executive Summary"
        assert len(document.sections[0].blocks) == 2
        assert document.sections[0].blocks[0].block_type == BlockType.HEADING
        assert document.sections[0].blocks[1].block_type == BlockType.PARAGRAPH
        assert document.sections[1].title == "Charts"
        chart_block = document.sections[1].blocks[0]
        assert chart_block.block_type == BlockType.CHART
        assert chart_block.chart is not None
        assert chart_block.chart.description == "Revenue by quarter"

        asset_refs = document.get_all_asset_refs()
        assert len(asset_refs) == 1
        assert asset_refs[0].status == "pending"
        assert asset_refs[0].asset_type == AssetType.CHART

    @pytest.mark.anyio
    async def test_agent_to_renderer_integration(
        self,
        sample_document_model: DocumentModel,
    ):
        """RendererFactory.render() с реальным DocumentModel."""
        with patch.object(MarpGenerator, "generate") as mock_marp:
            mock_marp.return_value = """---
marp: true
---

# Test Report

This is a test report.
"""

            asset_resolver = AssetResolver(
                asset_manager=AssetManager(),
                chart_builder=ChartBuilder(),
                diagram_builder=DiagramBuilder(),
                formula_builder=FormulaBuilder(),
            )
            marp_generator = MarpGenerator(asset_resolver=asset_resolver)
            renderer_factory = RendererFactory(
                marp_generator=marp_generator,
                asset_resolver=asset_resolver,
            )

            render_result = await renderer_factory.render(sample_document_model, "pdf")
            assert render_result is not None
            mock_marp.assert_called_once_with(sample_document_model)

    @pytest.mark.anyio
    async def test_agent_to_storage_integration(
        self,
        temp_output_file: str,
    ):
        """StorageProvider.upload() с реальным файлом."""
        storage = MockStorageProvider()
        with open(temp_output_file, "rb") as f:
            storage_path = await storage.upload(
                file_path="artifacts/1/test_report.pdf",
                content=f,
            )
        assert storage_path is not None
        assert len(storage_path) > 0
        assert os.path.exists(storage_path)

    @pytest.mark.anyio
    async def test_full_pipeline_with_mocked_externals(
        self,
        db_session: Session,
        temp_output_file: str,
    ):
        """Полный pipeline с mock'ами только для внешних зависимостей."""
        # Создаём User и ChatSession для FK constraints в _save_artifact_v2
        db_user = User(id=1, email="pipeline@test.com", username="pipeline_user",
                       hashed_password="x", is_active=True)
        db_session.add(db_user)
        from app.models.chat import ChatSession
        chat_session = ChatSession(user_id=1, title="Pipeline Test Session")
        db_session.add(chat_session)
        db_session.commit()
        db_session.refresh(chat_session)

        plan = ArtifactPlan(
            title="Full Pipeline Test",
            artifact_type="pdf",
            sections=[
                {
                    "title": "Introduction",
                    "blocks": [
                        {"type": "heading", "level": 1, "text": "Introduction"},
                        {"type": "paragraph", "text": "Full pipeline integration test."},
                    ],
                },
            ],
            reasoning="Integration test",
        )

        template_manager = TemplateManager(db=db_session)
        theme_manager = ThemeManager(db=db_session)
        document_builder = DocumentBuilder()
        document_validator = DocumentValidator()
        artifact_auto_fix = ArtifactAutoFix()
        render_validator = RenderValidator()

        asset_resolver = AssetResolver(
            asset_manager=AssetManager(),
            chart_builder=ChartBuilder(),
            diagram_builder=DiagramBuilder(),
            formula_builder=FormulaBuilder(),
        )
        marp_generator = MarpGenerator(asset_resolver=asset_resolver)
        renderer_factory = RendererFactory(
            marp_generator=marp_generator,
            asset_resolver=asset_resolver,
        )

        agent = ArtifactGeneratorAgent(
            db_session=db_session,
            storage=MockStorageProvider(),
            template_manager=template_manager,
            theme_manager=theme_manager,
            document_builder=document_builder,
            document_validator=document_validator,
            artifact_auto_fix=artifact_auto_fix,
            renderer_factory=renderer_factory,
            render_validator=render_validator,
        )

        agent._plan_artifact = AsyncMock(return_value=plan)  # type: ignore[assignment]

        with patch.object(MarpRenderer, "render") as mock_marp_render:
            mock_marp_render.return_value = RenderResult(
                success=True,
                file_path=temp_output_file,
                file_size=os.path.getsize(temp_output_file),
                mime_type="application/pdf",
            )

            result = await agent.generate(
                query="Full pipeline test",
                context="Test context data",
                user_id=1,
                session_id=chat_session.id,
                template_name="corporate_report",
                theme_name="corporate",
                output_format="pdf",
            )

        events = result.get("events", [])
        phase_starts = [e for e in events if e["event"] == "phase_start"]
        phase_completes = [e for e in events if e["event"] == "phase_complete"]
        artifact_ready_events = [e for e in events if e["event"] == "artifact_ready"]

        # Фаза saving не имеет phase_complete — вместо неё artifact_ready
        # Поэтому ожидаем 5 phase_complete + artifact_ready для saving
        assert len(phase_starts) >= 6, (
            f"Expected ≥6 phase starts, got {len(phase_starts)}"
        )
        assert len(phase_completes) >= 5, (
            f"Expected ≥5 phase completes, got {len(phase_completes)}"
        )
        assert len(artifact_ready_events) >= 1, (
            "Expected at least 1 artifact_ready event (saving phase)"
        )

        if result["status"] == "ready":
            assert result["project_id"] is not None, "project_id should not be None"
            assert result["version_id"] is not None, "version_id should not be None"
            assert result["artifact_id"] is not None, "artifact_id should not be None"