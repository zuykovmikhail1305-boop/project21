"""Artifact Generator Agent v2: генерация артефактов (PDF, презентации, отчёты).

Архитектура v2 (один LLM-вызов):
1. Planning — LLM → ArtifactPlan (смысловая структура, без кода/Markdown)
2. Document Building — DocumentBuilder.build(plan, context, theme) → DocumentModel
3. Document Validation — DocumentValidator.validate(document) → auto-fix если можно
4. Rendering — RendererFactory.render(document, format) → RenderResult
5. Render Validation — RenderValidator.validate(render_result) → логирование
6. Save — v2 таблицы (artifact_projects, artifact_versions, artifact_assets) + StorageProvider
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

try:
    from langchain_gigachat import GigaChat as GigaChatLangChain
except Exception:  # pragma: no cover - optional dependency guard
    GigaChatLangChain = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None

from app.core import config
from app.models.artifact_v2 import ArtifactProject, ArtifactVersion, ArtifactAsset
from app.services.artifact.models import (
    ArtifactPlan,
    ArtifactContext,
    DocumentModel,
    Theme,
    ValidationResult,
    RenderResult,
    ArtifactStatus,
    AssetType,
)
from app.services.artifact.document_builder import DocumentBuilder
from app.services.artifact.marp_generator import MarpGenerator
from app.services.artifact.renderer_factory import RendererFactory
from app.services.artifact.asset_resolver import AssetResolver
from app.services.artifact.asset_manager import AssetManager
from app.services.artifact.validator import DocumentValidator, ArtifactAutoFix, RenderValidator
from app.services.artifact.template_manager import TemplateManager
from app.services.artifact.theme_manager import ThemeManager
from app.services.artifact.chart_builder import ChartBuilder
from app.services.artifact.diagram_builder import DiagramBuilder
from app.services.artifact.formula_builder import FormulaBuilder
from app.services.storage import MockStorageProvider, StorageProvider

logger = logging.getLogger(__name__)


# === Промпт для Phase 1 (единственный LLM-вызов) ===

ARTIFACT_PLANNING_PROMPT = """Ты — архитектор корпоративных документов. Твоя задача — спроектировать структуру документа на основе запроса пользователя и контекста.

## Правила
1. Ты НЕ пишешь код, НЕ генерируешь Markdown, НЕ указываешь типы графиков.
2. Ты определяешь ТОЛЬКО смысловую структуру: заголовки секций, типы блоков, описания.
3. Каждая секция содержит список блоков. Доступные типы блоков:
   - heading — заголовок (level: 1-6, text: текст)
   - paragraph — абзац (text: текст)
   - table — таблица (headers: список колонок, rows: список строк, data_source: описание данных)
   - chart — график (description: что показать, data_source: откуда данные, columns: какие колонки)
   - diagram — диаграмма (engine: "mermaid", code: код диаграммы)
   - formula — формула (latex: LaTeX-код)
   - code — код (language: язык, code: код)
   - quote — цитата (text: текст, source: источник)
   - image — изображение (src: путь, alt: описание)
   - bullet_list — маркированный список (items: список строк)
   - columns — колонки (columns: [{{blocks: [...]}}])
   - callout — выделенный блок (style: "info"|"warning"|"error"|"success", text: текст)

4. Для chart-блоков укажи:
   - description: что именно показать на графике (например, "Динамика выручки по месяцам")
   - data_source: откуда брать данные (например, "financial_data")
   - columns: какие колонки данных нужны (например, ["month", "revenue"])

5. Для table-блоков укажи headers и rows, если данные известны из контекста.

## Шаблон документа
Используй шаблон "{template_name}" как основу для структуры.

## Запрос пользователя
{query}

## Контекст из документов
{context}

## Твоя задача
Верни структурированный план документа с секциями и блоками.
"""


class ArtifactGeneratorAgent:
    """Агент для генерации артефактов (PDF, презентации, отчёты) — архитектура v2.

    Использует один LLM-вызов для планирования, затем программную сборку документа,
    рендеринг через Marp CLI и сохранение в v2 таблицы.
    """

    def __init__(
        self,
        storage: Optional[StorageProvider] = None,
        db_session: Optional[Session] = None,
        template_manager: Optional[TemplateManager] = None,
        theme_manager: Optional[ThemeManager] = None,
        document_builder: Optional[DocumentBuilder] = None,
        document_validator: Optional[DocumentValidator] = None,
        artifact_auto_fix: Optional[ArtifactAutoFix] = None,
        renderer_factory: Optional[RendererFactory] = None,
        render_validator: Optional[RenderValidator] = None,
    ):
        self.storage = storage or MockStorageProvider()
        self.db_session = db_session

        # Менеджеры шаблонов и тем
        self.template_manager = template_manager or TemplateManager(db=db_session)
        self.theme_manager = theme_manager or ThemeManager(db=db_session)

        # Document pipeline
        self.document_builder = document_builder or DocumentBuilder()
        self.document_validator = document_validator or DocumentValidator()
        self.artifact_auto_fix = artifact_auto_fix or ArtifactAutoFix()

        # Render pipeline
        self.renderer_factory = renderer_factory or RendererFactory()
        self.render_validator = render_validator or RenderValidator()

        # LLM chains: GigaChat (приоритет) или ChatOpenAI (fallback)
        self._gigachat_llm = None
        self._openai_llm = None
        self.planning_chain = None

        # 1. GigaChat (langchain-gigachat) — приоритет
        self._init_gigachat()

        # 2. ChatOpenAI — fallback
        self._init_openai()

        # 3. Выбираем, какой LLM использовать для chain
        self.llm = self._gigachat_llm or self._openai_llm
        if self.llm is not None:
            self.planning_chain = self.llm.with_structured_output(ArtifactPlan)

    def _init_gigachat(self) -> None:
        """Инициализировать GigaChat через langchain-gigachat."""
        if GigaChatLangChain is None:
            return

        has_creds = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )
        if not has_creds:
            return

        try:
            self._gigachat_llm = GigaChatLangChain(
                credentials=config.GIGACHAT_CREDENTIALS,
                scope=config.GIGACHAT_SCOPE,
                base_url=config.GIGACHAT_API_URL,
                auth_url=config.GIGACHAT_AUTH_URL,
                model=config.GIGACHAT_MODEL,
                temperature=0.1,
                verify_ssl_certs=False,
                timeout=30,
            )
        except Exception:
            self._gigachat_llm = None

    def _init_openai(self) -> None:
        """Инициализировать ChatOpenAI как fallback."""
        if ChatOpenAI is None:
            return

        try:
            self._openai_llm = ChatOpenAI(
                model=config.OPENAI_MODEL,
                temperature=0.1,
                api_key=config.OPENAI_API_KEY,  # type: ignore[arg-type]
                base_url=config.OPENAI_API_BASE,
            )
        except Exception:
            self._openai_llm = None

    def _make_event(
        self,
        event_type: str,
        phase: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Создать SSE-совместимое событие.

        Args:
            event_type: Тип события (phase_start, phase_complete, artifact_ready, ...).
            phase: Название фазы (planning, document_building, ...).
            data: Дополнительные данные события.

        Returns:
            dict с полями event, phase, timestamp, data.
        """
        event: dict[str, Any] = {
            "event": event_type,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if data:
            event["data"] = data
        return event

    def _chunks_to_dataframes(
        self,
        context: str,
    ) -> dict[str, pd.DataFrame]:
        """Преобразовать строковый контекст из RAG в dict[str, DataFrame].

        Парсит JSON-подобные таблицы из контекста. Если контекст содержит
        структурированные данные в формате JSON, конвертирует их в DataFrame.
        Если данных нет — возвращает пустой словарь.

        Args:
            context: Строковый контекст из RAG (answer + chunks).

        Returns:
            dict[str, pd.DataFrame] — имя источника → DataFrame.
        """
        dataframes: dict[str, pd.DataFrame] = {}

        if not context:
            return dataframes

        # Пробуем распарсить весь контекст как JSON
        try:
            parsed = json.loads(context)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if isinstance(value, list) and len(value) > 0:
                        try:
                            df = pd.DataFrame(value)
                            dataframes[key] = df
                            logger.info(
                                "Parsed DataFrame from context: key=%s shape=%s",
                                key, df.shape,
                            )
                        except Exception as e:
                            logger.debug("Failed to parse key %s as DataFrame: %s", key, e)
            elif isinstance(parsed, list) and len(parsed) > 0:
                try:
                    df = pd.DataFrame(parsed)
                    dataframes["data"] = df
                    logger.info("Parsed DataFrame from context list: shape=%s", df.shape)
                except Exception as e:
                    logger.debug("Failed to parse list as DataFrame: %s", e)
        except (json.JSONDecodeError, ValueError):
            pass

        # Если JSON не распарсился — ищем JSON-блоки в тексте
        if not dataframes:
            import re
            json_blocks = re.findall(
                r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```',
                context,
                re.DOTALL,
            )
            for i, block in enumerate(json_blocks):
                try:
                    parsed = json.loads(block)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        df = pd.DataFrame(parsed)
                        dataframes[f"data_{i}"] = df
                        logger.info(
                            "Parsed DataFrame from JSON block %d: shape=%s",
                            i, df.shape,
                        )
                    elif isinstance(parsed, dict):
                        for key, value in parsed.items():
                            if isinstance(value, list) and len(value) > 0:
                                try:
                                    df = pd.DataFrame(value)
                                    dataframes[key] = df
                                except Exception:
                                    pass
                except (json.JSONDecodeError, ValueError):
                    continue

        logger.info(
            "Context parsed into %d DataFrames",
            len(dataframes),
        )
        return dataframes

    async def generate(
        self,
        query: str,
        context: str,
        user_id: int,
        session_id: int,
        message_id: Optional[int] = None,
        template_name: str = "corporate_report",
        theme_name: str = "corporate",
        output_format: str = "pdf",
    ) -> dict[str, Any]:
        """Полный цикл генерации артефакта (v2).

        Args:
            query: Запрос пользователя.
            context: Контекст из документов (результат SearchRAGAgent).
            user_id: ID пользователя.
            session_id: ID сессии чата.
            message_id: ID сообщения-источника (опционально).
            template_name: Имя шаблона документа.
            theme_name: Имя темы оформления.
            output_format: Целевой формат: pdf, pptx, html, md.

        Returns:
            dict с результатами генерации.
        """
        # Инициализируем результат
        result: dict[str, Any] = {
            "status": "generating",
            "project_id": None,
            "version_id": None,
            "artifact_id": None,
            "title": "",
            "artifact_type": output_format,
            "error": None,  # для обратной совместимости с orchestrator.py
            "error_message": None,
            "events": [],
        }

        if self.llm is None:
            result["status"] = "error"
            result["error"] = "LLM provider is not available"
            result["error_message"] = "LLM provider is not available"
            return result

        try:
            # ================================================================
            # Phase 1: Planning — единственный LLM-вызов
            # ================================================================
            logger.info("Phase 1: Planning artifact structure (v2)")
            result["events"].append(
                self._make_event("phase_start", "planning")
            )

            plan = await self._plan_artifact(
                query=query,
                context=context,
                template_name=template_name,
            )
            result["title"] = plan.title
            result["artifact_type"] = plan.artifact_type

            result["events"].append(
                self._make_event("phase_complete", "planning", {
                    "title": plan.title,
                    "artifact_type": plan.artifact_type,
                    "sections_count": len(plan.sections),
                })
            )
            logger.info(
                "Planning complete: title=%s type=%s sections=%d",
                plan.title, plan.artifact_type, len(plan.sections),
            )

            # ================================================================
            # Phase 2: Document Building
            # ================================================================
            logger.info("Phase 2: Building document model")
            result["events"].append(
                self._make_event("phase_start", "document_building")
            )

            # Получаем тему
            theme = self.theme_manager.get_theme(theme_name)
            if theme is None:
                theme = self.theme_manager.get_default_theme()
                logger.warning("Theme '%s' not found, using default", theme_name)

            # Создаём контекст артефакта
            artifact_context = ArtifactContext(
                language="ru",
                company="",
                timezone="Europe/Moscow",
                currency="RUB",
                theme_name=theme_name,
            )

            document = self.document_builder.build(
                plan=plan,
                context=artifact_context,
                theme=theme,
            )

            result["events"].append(
                self._make_event("phase_complete", "document_building", {
                    "sections": len(document.sections),
                    "blocks": sum(len(s.blocks) for s in document.sections),
                    "asset_refs": len(document.get_all_asset_refs()),
                })
            )
            logger.info(
                "Document built: sections=%d blocks=%d assets=%d",
                len(document.sections),
                sum(len(s.blocks) for s in document.sections),
                len(document.get_all_asset_refs()),
            )

            # ================================================================
            # Phase 3: Document Validation
            # ================================================================
            logger.info("Phase 3: Validating document model")
            result["events"].append(
                self._make_event("phase_start", "document_validation")
            )

            validation_result = await self.document_validator.validate(document)

            if not validation_result.passed:
                # Проверяем, можно ли автоматически исправить
                fixable_errors = [
                    e for e in validation_result.errors
                    if e.check_name in ("empty_blocks", "section_structure")
                ]
                critical_errors = [
                    e for e in validation_result.errors
                    if e.check_name not in ("empty_blocks", "section_structure")
                ]

                if fixable_errors and not critical_errors:
                    logger.info(
                        "Auto-fixing %d fixable validation errors",
                        len(fixable_errors),
                    )
                    document = await self.artifact_auto_fix.fix(
                        document, validation_result,
                    )
                    # Перевалидируем после фикса
                    validation_result = await self.document_validator.validate(document)
                    logger.info(
                        "After auto-fix: passed=%s errors=%d",
                        validation_result.passed,
                        len(validation_result.errors),
                    )

                if not validation_result.passed:
                    error_msg = (
                        f"Document validation failed: "
                        f"{'; '.join(e.message for e in validation_result.errors[:5])}"
                    )
                    logger.error(error_msg)
                    result["status"] = "error"
                    result["error"] = error_msg
                    result["error_message"] = error_msg
                    result["events"].append(
                        self._make_event("phase_complete", "document_validation", {
                            "passed": False,
                            "errors": len(validation_result.errors),
                        })
                    )
                    result["events"].append(
                        self._make_event("artifact_error", "document_validation", {
                            "error": error_msg,
                        })
                    )
                    return result

            result["events"].append(
                self._make_event("phase_complete", "document_validation", {
                    "passed": True,
                    "checks": len(validation_result.checks),
                })
            )
            logger.info("Document validation passed: %d checks", len(validation_result.checks))

            # ================================================================
            # Phase 4: Rendering
            # ================================================================
            logger.info("Phase 4: Rendering to %s", output_format)
            result["events"].append(
                self._make_event("phase_start", "rendering", {
                    "format": output_format,
                })
            )

            # Преобразуем контекст в DataFrame для AssetResolver
            dataframes = self._chunks_to_dataframes(context)

            # Создаём AssetResolver с данными
            asset_resolver = AssetResolver(
                asset_manager=AssetManager(),
                chart_builder=ChartBuilder(),
                diagram_builder=DiagramBuilder(),
                formula_builder=FormulaBuilder(),
            )

            # Разрешаем все ассеты (lazy — только если renderer до них дойдёт)
            asset_refs = document.get_all_asset_refs()
            if asset_refs:
                logger.info("Resolving %d asset references", len(asset_refs))
                await asset_resolver.resolve_all(asset_refs, dataframes, theme)

            # Создаём RendererFactory с asset_resolver'ом
            renderer_factory = RendererFactory(
                marp_generator=MarpGenerator(asset_resolver=asset_resolver),
                asset_resolver=asset_resolver,
            )

            render_result = await renderer_factory.render(document, output_format)

            if not render_result.success:
                error_msg = f"Render failed: {render_result.error}"
                logger.error(error_msg)
                result["status"] = "error"
                result["error"] = error_msg
                result["error_message"] = error_msg
                result["events"].append(
                    self._make_event("phase_complete", "rendering", {
                        "success": False,
                        "error": render_result.error,
                    })
                )
                result["events"].append(
                    self._make_event("artifact_error", "rendering", {
                        "error": error_msg,
                    })
                )
                return result

            result["events"].append(
                self._make_event("phase_complete", "rendering", {
                    "success": True,
                    "file_path": render_result.file_path,
                    "file_size": render_result.file_size,
                })
            )
            logger.info(
                "Render complete: path=%s size=%d",
                render_result.file_path, render_result.file_size,
            )

            # ================================================================
            # Phase 5: Render Validation
            # ================================================================
            logger.info("Phase 5: Validating render result")
            result["events"].append(
                self._make_event("phase_start", "render_validation")
            )

            render_validation = await self.render_validator.validate(render_result)

            if not render_validation.passed:
                logger.warning(
                    "Render validation issues: %d errors",
                    len(render_validation.errors),
                )
                # Не прерываем — файл уже создан, только логируем

            result["events"].append(
                self._make_event("phase_complete", "render_validation", {
                    "passed": render_validation.passed,
                    "checks": len(render_validation.checks),
                    "errors": len(render_validation.errors),
                })
            )

            # ================================================================
            # Phase 6: Save
            # ================================================================
            logger.info("Phase 6: Saving artifact")
            result["events"].append(
                self._make_event("phase_start", "saving")
            )

            save_result = await self._save_artifact_v2(
                render_result=render_result,
                document=document,
                plan=plan,
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                template_name=template_name,
                theme_name=theme_name,
                output_format=output_format,
                validation_result=validation_result,
                render_validation=render_validation,
            )

            result["status"] = "ready"
            result["project_id"] = save_result.get("project_id")
            result["version_id"] = save_result.get("version_id")
            result["artifact_id"] = save_result.get("artifact_id")

            result["events"].append(
                self._make_event("artifact_ready", "saving", {
                    "project_id": save_result.get("project_id"),
                    "version_id": save_result.get("version_id"),
                    "artifact_id": save_result.get("artifact_id"),
                    "type": output_format,
                    "url": save_result.get("download_url"),
                    "filename": save_result.get("filename"),
                    "size": render_result.file_size,
                })
            )

            logger.info(
                "Artifact generated successfully: project=%s version=%s file=%s",
                save_result.get("project_id"),
                save_result.get("version_id"),
                save_result.get("filename"),
            )

        except Exception as e:
            logger.exception("Artifact generation failed (v2)")
            result["status"] = "error"
            result["error"] = str(e)
            result["error_message"] = str(e)
            result["events"].append(
                self._make_event("artifact_error", "unknown", {
                    "error": str(e),
                })
            )

        return result

    async def _plan_artifact(
        self,
        query: str,
        context: str,
        template_name: str,
    ) -> ArtifactPlan:
        """Phase 1: Планирование структуры артефакта через LLM.

        Единственный LLM-вызов во всём пайплайне.
        LLM возвращает ArtifactPlan — только смысловую структуру.

        Args:
            query: Запрос пользователя.
            context: Контекст из документов.
            template_name: Имя шаблона.

        Returns:
            ArtifactPlan с секциями и блоками.
        """
        if self.planning_chain is None:
            # Fallback: создаём план из шаблона
            logger.warning("LLM not available, using template fallback")
            template_plan = self.template_manager.apply_template(
                template_name=template_name,
                variables={"title": query[:100]},
            )
            return template_plan

        # Обрезаем контекст до разумного размера
        truncated_context = context[:50000] if context else "Нет контекста"

        prompt = ARTIFACT_PLANNING_PROMPT.format(
            query=query,
            context=truncated_context,
            template_name=template_name,
        )

        # Pylance: planning_chain narrowed to not-None by the check above
        chain = self.planning_chain
        llm_plan = await chain.ainvoke(prompt)  # type: ignore[arg-type]

        # with_structured_output возвращает Pydantic модель
        if isinstance(llm_plan, ArtifactPlan):
            return llm_plan

        # Если вернулся dict — конвертируем
        plan_data = llm_plan if isinstance(llm_plan, dict) else llm_plan.model_dump()  # type: ignore[union-attr]
        return ArtifactPlan(
            title=plan_data.get("title", "Артефакт"),
            artifact_type=plan_data.get("artifact_type", "pdf"),
            sections=plan_data.get("sections", []),
            reasoning=plan_data.get("reasoning", ""),
        )

    async def _save_artifact_v2(
        self,
        render_result: RenderResult,
        document: DocumentModel,
        plan: ArtifactPlan,
        user_id: int,
        session_id: int,
        message_id: Optional[int] = None,
        template_name: str = "corporate_report",
        theme_name: str = "corporate",
        output_format: str = "pdf",
        validation_result: Optional[ValidationResult] = None,
        render_validation: Optional[ValidationResult] = None,
    ) -> dict[str, Any]:
        """Phase 6: Сохранение артефакта в v2 таблицы и StorageProvider.

        Создаёт:
        - artifact_projects — проект артефакта
        - artifact_versions — версия с DocumentModel
        - artifact_assets — ассеты (если есть)
        - Файл через StorageProvider

        Args:
            render_result: Результат рендеринга.
            document: DocumentModel.
            plan: ArtifactPlan от LLM.
            user_id: ID пользователя.
            session_id: ID сессии чата.
            message_id: ID сообщения-источника.
            template_name: Имя шаблона.
            theme_name: Имя темы.
            output_format: Целевой формат.
            validation_result: Результат валидации документа.
            render_validation: Результат валидации рендера.

        Returns:
            dict с project_id, version_id, artifact_id, filename, download_url.
        """
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            raise RuntimeError("Render result file not found")

        # Определяем имя файла
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in plan.title)
        filename = f"{safe_title[:50]}.{output_format}"

        # Сохраняем через StorageProvider
        with open(render_result.file_path, "rb") as f:
            storage_path = await self.storage.upload(
                file_path=f"artifacts/{user_id}/{filename}",
                content=f,
            )

        file_size = os.path.getsize(render_result.file_path)

        # Очищаем временный файл
        try:
            os.unlink(render_result.file_path)
        except OSError:
            pass

        # Сохраняем в v2 таблицы, если есть БД
        project_id: Optional[int] = None
        version_id: Optional[int] = None
        artifact_id: Optional[int] = None

        if self.db_session is not None:
            try:
                # 1. Создаём проект
                project = ArtifactProject(
                    user_id=user_id,
                    session_id=session_id,
                    title=plan.title,
                    template_name=template_name,
                    current_version=1,
                    context={
                        "theme_name": theme_name,
                        "output_format": output_format,
                        "language": "ru",
                        "timezone": "Europe/Moscow",
                        "currency": "RUB",
                    },
                )
                self.db_session.add(project)
                self.db_session.flush()  # получаем project.id

                # 2. Создаём версию
                version = ArtifactVersion(
                    project_id=project.id,
                    version_number=1,
                    status=ArtifactStatus.READY,
                    document_model=document.model_dump(mode="json"),
                    dependency_graph=document.dependency_graph.model_dump(mode="json"),
                    storage_path=storage_path,
                    file_size=file_size,
                    artifact_type=output_format,
                    document_validation=(
                        validation_result.model_dump(mode="json")
                        if validation_result else None
                    ),
                    render_validation=(
                        render_validation.model_dump(mode="json")
                        if render_validation else None
                    ),
                )
                self.db_session.add(version)
                self.db_session.flush()  # получаем version.id

                # 3. Сохраняем ассеты
                asset_refs = document.get_all_asset_refs()
                for ref in asset_refs:
                    if ref.status == "resolved" and ref.resolved_asset:
                        asset = ref.resolved_asset
                        # Сохраняем ассет в StorageProvider
                        if os.path.exists(asset.file_path):
                            with open(asset.file_path, "rb") as af:
                                asset_storage_path = await self.storage.upload(
                                    file_path=f"artifacts/{user_id}/assets/{asset.asset_id}_{asset.name}",
                                    content=af,
                                )

                            asset_record = ArtifactAsset(
                                asset_id=asset.asset_id,
                                version_id=version.id,
                                asset_type=asset.asset_type,
                                name=asset.name,
                                mime_type=asset.mime_type,
                                storage_path=asset_storage_path,
                                asset_metadata=asset.metadata,
                                size_bytes=asset.size_bytes,
                            )
                            self.db_session.add(asset_record)

                self.db_session.commit()
                self.db_session.refresh(project)
                self.db_session.refresh(version)

                project_id = int(project.id)  # type: ignore[arg-type]
                version_id = int(version.id)  # type: ignore[arg-type]
                artifact_id = int(version.id)  # type: ignore[arg-type]  # version.id как artifact_id для совместимости

                logger.info(
                    "Saved to v2 tables: project=%d version=%d",
                    project_id, version_id,
                )

            except Exception as e:
                self.db_session.rollback()
                logger.error("Failed to save to v2 tables: %s", e)
                # Не прерываем — файл уже сохранён в StorageProvider
                # Просто возвращаем без ID из БД

        return {
            "project_id": project_id,
            "version_id": version_id,
            "artifact_id": artifact_id,
            "filename": filename,
            "storage_path": storage_path,
            "download_url": f"/api/v1/artifacts/download/{filename}",
        }
