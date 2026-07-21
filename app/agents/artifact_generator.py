"""Artifact Generator Agent: генерация артефактов (PDF, презентации, отчёты).

Агент работает в 5 фаз:
1. Планирование — LLM определяет структуру артефакта и выбирает движок графиков
2. Генерация графиков — LLM пишет код Matplotlib/Plotly → sandbox выполняет
3. Генерация Marp Markdown — LLM создаёт Markdown со вставками графиков
4. Рендеринг — Marp CLI конвертирует Markdown в целевой формат
5. Сохранение — файл сохраняется в StorageProvider
"""

import json
import logging
import os
import shutil
from typing import Optional

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency guard
    ChatOpenAI = None

from pydantic import BaseModel, Field

from app.core import config
from app.services.artifact.base import (
    ArtifactPlan,
    ArtifactContent,
    ChartPlan,
    SandboxResult,
    RenderResult,
)
from app.services.artifact.chart_executor import SubprocessSandbox
from app.services.artifact.marp_renderer import MarpRenderer
from app.services.storage import MockStorageProvider, StorageProvider

logger = logging.getLogger(__name__)


# === Pydantic модели для структурированного вывода LLM ===


class LLMArtifactPlan(BaseModel):
    """Структурированный план артефакта от LLM."""
    title: str = Field(description="Название артефакта")
    artifact_type: str = Field(
        description="Тип артефакта: pdf, pptx, docx, md, html",
        pattern=r"^(pdf|pptx|docx|md|html)$",
    )
    chart_engine: str = Field(
        description="Движок графиков: matplotlib (по умолчанию) или plotly (если явно запрошена интерактивность)",
        pattern=r"^(matplotlib|plotly)$",
    )
    sections: list[dict] = Field(
        description="Список разделов артефакта. Каждый: {title, description, requires_chart или null}"
    )
    charts: list[dict] = Field(
        description="Список графиков. Каждый: {chart_type, title, data_source}"
    )
    reasoning: str = Field(description="Обоснование выбора структуры и движка графиков")


class LLMChartCode(BaseModel):
    """Код графика от LLM."""
    code: str = Field(description="Чистый Python-код для генерации графика")
    engine: str = Field(
        description="Используемый движок: matplotlib или plotly",
        pattern=r"^(matplotlib|plotly)$",
    )


class LLMMarkdownContent(BaseModel):
    """Marp-совместимый Markdown контент от LLM."""
    markdown: str = Field(description="Marp-совместимый Markdown с вставками графиков")


# === Промпты ===

class ArtifactGeneratorAgent:
    """Агент для генерации артефактов (PDF, презентации, отчёты)."""

    def __init__(
        self,
        storage: Optional[StorageProvider] = None,
        sandbox: Optional[SubprocessSandbox] = None,
        marp: Optional[MarpRenderer] = None,
    ):
        self.storage = storage or MockStorageProvider()
        self.sandbox = sandbox or SubprocessSandbox()
        self.marp = marp or MarpRenderer()

        self.llm = None
        self.planning_chain = None
        self.chart_code_chain = None
        self.marp_chain = None

        if ChatOpenAI is not None:
            try:
                self.llm = ChatOpenAI(
                    model=config.OPENAI_MODEL,
                    temperature=0.1,
                    api_key=config.OPENAI_API_KEY,  # type: ignore[arg-type]
                    base_url=config.OPENAI_API_BASE,
                )
            except Exception:
                self.llm = None

    async def generate(
        self,
        query: str,
        context: str,
        user_id: int,
        session_id: int,
        message_id: Optional[int] = None,
    ) -> dict:
        """Полный цикл генерации артефакта.

        Args:
            query: Запрос пользователя.
            context: Контекст из документов (результат SearchRAGAgent).
            user_id: ID пользователя.
            session_id: ID сессии чата.
            message_id: ID сообщения-источника (опционально).

        Returns:
            dict с результатами генерации.
        """
        result = {
            "status": "generating",
            "artifact_id": None,
            "title": None,
            "artifact_type": None,
            "error": None,
            "events": [],  # для SSE
        }

        if self.llm is None:
            result["status"] = "error"
            result["error"] = "LLM provider is not available"
            return result

        try:
            # === Фаза 1: Планирование ===
            logger.info("Phase 1: Planning artifact structure")
            result["events"].append({"event": "artifact_planning", "data": {"phase": "planning"}})

            plan = await self._plan_artifact(query, context)
            result["title"] = plan.title
            result["artifact_type"] = plan.artifact_type

            result["events"].append({
                "event": "artifact_planning",
                "data": {
                    "type": plan.artifact_type,
                    "title": plan.title,
                    "sections": [s.model_dump() for s in plan.sections],
                    "charts": [c.model_dump() for c in plan.charts],
                    "chart_engine": plan.chart_engine,
                },
            })

            # === Фаза 2: Генерация графиков ===
            chart_paths = []
            interactive_paths = []

            if plan.charts:
                logger.info(f"Phase 2: Generating {len(plan.charts)} charts using {plan.chart_engine}")
                for i, chart in enumerate(plan.charts):
                    result["events"].append({
                        "event": "chart_generating",
                        "data": {
                            "chart_index": i,
                            "chart_title": chart.title,
                            "total_charts": len(plan.charts),
                            "engine": plan.chart_engine,
                        },
                    })

                    chart_result = await self._generate_chart(chart, context, plan.chart_engine)
                    if chart_result.success:
                        for fp in chart_result.output_files:
                            if fp.endswith(".html"):
                                interactive_paths.append(fp)
                            else:
                                chart_paths.append(fp)

                        result["events"].append({
                            "event": "chart_ready",
                            "data": {
                                "chart_index": i,
                                "chart_path": chart_result.output_files[0] if chart_result.output_files else None,
                            },
                        })
                    else:
                        logger.warning(f"Chart {i} generation failed: {chart_result.error}")

            # === Фаза 3: Генерация Marp Markdown ===
            logger.info("Phase 3: Generating Marp markdown")
            result["events"].append({
                "event": "artifact_progress",
                "data": {"percent": 60, "stage": "generating_content"},
            })

            content = await self._generate_markdown(plan, chart_paths, interactive_paths)

            # === Фаза 4: Рендеринг ===
            logger.info(f"Phase 4: Rendering to {plan.artifact_type}")
            result["events"].append({
                "event": "artifact_progress",
                "data": {"percent": 80, "stage": "rendering"},
            })

            render_result = await self._render(content, plan.artifact_type)

            if not render_result.success:
                raise RuntimeError(f"Render failed: {render_result.error}")

            # === Фаза 5: Сохранение ===
            logger.info("Phase 5: Saving artifact")
            result["events"].append({
                "event": "artifact_progress",
                "data": {"percent": 95, "stage": "saving"},
            })

            artifact_info = await self._save_artifact(
                render_result, plan, user_id, session_id, message_id,
            )

            result["status"] = "ready"
            result["artifact_id"] = artifact_info.get("id")
            result["events"].append({
                "event": "artifact_ready",
                "data": {
                    "id": artifact_info.get("id"),
                    "type": plan.artifact_type,
                    "url": artifact_info.get("download_url"),
                    "filename": artifact_info.get("filename"),
                    "size": render_result.file_size,
                },
            })

            logger.info(f"Artifact generated successfully: {artifact_info.get('filename')}")

        except Exception as e:
            logger.exception("Artifact generation failed")
            result["status"] = "error"
            result["error"] = str(e)
            result["events"].append({
                "event": "artifact_error",
                "data": {"error": str(e)},
            })

        return result

    async def _plan_artifact(self, query: str, context: str) -> ArtifactPlan:
        """Фаза 1: Планирование структуры артефакта."""
        llm_plan = await self.planning_chain.ainvoke({
            "query": query,
            "context": context[:50000] if context else "Нет контекста",
        })

        # with_structured_output возвращает Pydantic модель (type checker видит dict — false positive)
        plan_data = llm_plan if isinstance(llm_plan, dict) else llm_plan.model_dump()  # type: ignore[union-attr]

        # Конвертируем LLM-план в нашу модель
        sections = []
        for s in plan_data.get("sections", []):
            sections.append({
                "title": s.get("title", ""),
                "description": s.get("description", ""),
                "requires_chart": s.get("requires_chart"),
            })

        charts = []
        for i, c in enumerate(plan_data.get("charts", [])):
            charts.append(ChartPlan(
                chart_index=i,
                chart_type=c.get("chart_type", "bar"),
                title=c.get("title", f"График {i + 1}"),
                data_source=c.get("data_source", ""),
                engine=plan_data.get("chart_engine", "matplotlib"),
            ))

        return ArtifactPlan(
            title=plan_data.get("title", "Артефакт"),
            artifact_type=plan_data.get("artifact_type", "pdf"),
            chart_engine=plan_data.get("chart_engine", "matplotlib"),
            sections=sections,
            charts=charts,
        )

    async def _generate_chart(
        self,
        chart: ChartPlan,
        context: str,
        engine: str,
    ) -> SandboxResult:
        """Фаза 2: Генерация одного графика."""
        # LLM генерирует код
        llm_code = await self.chart_code_chain.ainvoke({
            "engine": engine,
            "chart_index": chart.chart_index,
            "chart_title": chart.title,
            "chart_description": chart.data_source,
            "data": context[:30000] if context else "Нет данных",
        })

        # with_structured_output возвращает Pydantic модель
        code_data = llm_code if isinstance(llm_code, dict) else llm_code.model_dump()  # type: ignore[union-attr]
        code_str = code_data.get("code", "")

        # Выполняем код в sandbox
        result = self.sandbox.execute(code_str, chart.chart_index)
        return result

    async def _generate_markdown(
        self,
        plan: ArtifactPlan,
        chart_paths: list[str],
        interactive_paths: list[str],
    ) -> ArtifactContent:
        """Фаза 3: Генерация Marp Markdown."""
        # Формируем структуру для промпта
        structure = {
            "title": plan.title,
            "sections": [
                {
                    "title": s.title if isinstance(s, dict) else s.title,
                    "description": s.description if isinstance(s, dict) else s.description,
                }
                for s in plan.sections
            ],
        }

        chart_paths_str = "\n".join(chart_paths) if chart_paths else "Нет графиков"
        if interactive_paths:
            chart_paths_str += "\n\nИнтерактивные графики (Plotly):\n" + "\n".join(interactive_paths)

        llm_markdown = await self.marp_chain.ainvoke({
            "title": plan.title,
            "structure": json.dumps(structure, ensure_ascii=False),
            "chart_paths": chart_paths_str,
        })

        # with_structured_output возвращает Pydantic модель
        md_data = llm_markdown if isinstance(llm_markdown,
                                             dict) else llm_markdown.model_dump()  # type: ignore[union-attr]
        markdown_content = md_data.get("markdown", "")

        return ArtifactContent(
            title=plan.title,
            artifact_type=plan.artifact_type,
            markdown_content=markdown_content,
            chart_paths=chart_paths,
            interactive_chart_paths=interactive_paths,
        )

    async def _render(self, content: ArtifactContent, output_format: str) -> RenderResult:
        """Фаза 4: Рендеринг через Marp CLI."""
        return self.marp.render(content.markdown_content, output_format)

    async def _save_artifact(
        self,
        render_result: RenderResult,
        plan: ArtifactPlan,
        user_id: int,
        session_id: int,
        message_id: Optional[int] = None,
    ) -> dict:
        """Фаза 5: Сохранение артефакта в StorageProvider."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            raise RuntimeError("Render result file not found")

        # Определяем имя файла
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in plan.title)
        ext = plan.artifact_type
        filename = f"{safe_title[:50]}.{ext}"

        # Сохраняем через StorageProvider
        with open(render_result.file_path, "rb") as f:
            storage_path = await self.storage.upload(
                file_path=f"artifacts/{user_id}/{filename}",
                content=f,
            )

        # Очищаем временный файл
        os.unlink(render_result.file_path)

        return {
            "id": None,  # будет заполнено при сохранении в БД
            "filename": filename,
            "storage_path": storage_path,
            "download_url": f"/api/v1/artifacts/download/{filename}",
        }
