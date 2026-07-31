"""RendererFactory: выбор рендерера по формату.

DocumentModel → RendererFactory → PDFRenderer / PPTXRenderer / HTMLRenderer / MarkdownRenderer.
Каждый рендерер независим. Marp — одна из реализаций.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.artifact.asset_resolver import AssetResolver
from app.services.artifact.marp_generator import MarpGenerator
from app.services.artifact.marp_renderer import MarpRenderer
from app.services.artifact.models import DocumentModel, RenderResult

logger = logging.getLogger(__name__)


def _convert_render_result(old_result) -> RenderResult:
    """Конвертировать старый RenderResult (из base.py) в новый (из models.py)."""
    if isinstance(old_result, RenderResult):
        return old_result
    return RenderResult(
        success=old_result.success,
        file_path=old_result.file_path,
        file_size=old_result.file_size,
        mime_type=old_result.mime_type,
        error=old_result.error,
    )


class BaseRenderer:
    """Базовый класс для всех рендереров."""

    def __init__(
        self,
        marp_generator: Optional[MarpGenerator] = None,
        marp_renderer: Optional[MarpRenderer] = None,
        asset_resolver: Optional[AssetResolver] = None,
    ):
        self.marp_generator = marp_generator or MarpGenerator(asset_resolver=asset_resolver)
        self.marp_renderer = marp_renderer or MarpRenderer()
        self.asset_resolver = asset_resolver or AssetResolver()

    async def render(self, document: DocumentModel) -> RenderResult:
        """Рендерить документ."""
        raise NotImplementedError


class PDFRenderer(BaseRenderer):
    """PDFRenderer: DocumentModel → PDF через Marp."""

    async def render(self, document: DocumentModel) -> RenderResult:
        logger.info("Rendering PDF: %s", document.title)
        markdown = self.marp_generator.generate(document)
        result = self.marp_renderer.render(markdown, "pdf")
        return _convert_render_result(result)


class PPTXRenderer(BaseRenderer):
    """PPTXRenderer: DocumentModel → PPTX через Marp."""

    async def render(self, document: DocumentModel) -> RenderResult:
        logger.info("Rendering PPTX: %s", document.title)
        markdown = self.marp_generator.generate(document)
        result = self.marp_renderer.render(markdown, "pptx")
        return _convert_render_result(result)


class HTMLRenderer(BaseRenderer):
    """HTMLRenderer: DocumentModel → HTML через Marp."""

    async def render(self, document: DocumentModel) -> RenderResult:
        logger.info("Rendering HTML: %s", document.title)
        markdown = self.marp_generator.generate(document)
        result = self.marp_renderer.render(markdown, "html")
        return _convert_render_result(result)


class MarkdownRenderer(BaseRenderer):
    """MarkdownRenderer: DocumentModel → .md (прямой экспорт, без Marp)."""

    async def render(self, document: DocumentModel) -> RenderResult:
        logger.info("Rendering Markdown: %s", document.title)
        markdown = self.marp_generator.generate(document)

        # Сохраняем .md файл напрямую
        import os
        import uuid

        output_dir = "/tmp/artifacts"
        os.makedirs(output_dir, exist_ok=True)

        file_id = uuid.uuid4().hex[:12]
        output_path = os.path.join(output_dir, f"artifact_{file_id}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        file_size = os.path.getsize(output_path)
        logger.info("Markdown saved: %s (%d bytes)", output_path, file_size)

        return RenderResult(
            success=True,
            file_path=output_path,
            file_size=file_size,
            mime_type="text/markdown",
        )


class RendererFactory:
    """Фабрика рендереров. Выбирает по формату."""

    RENDERERS = {
        "pdf": PDFRenderer,
        "pptx": PPTXRenderer,
        "html": HTMLRenderer,
        "md": MarkdownRenderer,
    }

    def __init__(
        self,
        marp_generator: Optional[MarpGenerator] = None,
        marp_renderer: Optional[MarpRenderer] = None,
        asset_resolver: Optional[AssetResolver] = None,
    ):
        self.marp_generator = marp_generator
        self.marp_renderer = marp_renderer
        self.asset_resolver = asset_resolver

    def get_renderer(self, format: str) -> BaseRenderer:
        """Получить рендерер для указанного формата.

        Args:
            format: Целевой формат: pdf, pptx, html, md.

        Returns:
            BaseRenderer для указанного формата.

        Raises:
            ValueError: если формат не поддерживается.
        """
        cls = self.RENDERERS.get(format)
        if not cls:
            raise ValueError(
                f"Unsupported format: {format}. "
                f"Supported: {', '.join(self.RENDERERS.keys())}"
            )
        return cls(
            marp_generator=self.marp_generator,
            marp_renderer=self.marp_renderer,
            asset_resolver=self.asset_resolver,
        )

    async def render(self, document: DocumentModel, format: str) -> RenderResult:
        """Рендерить документ в указанный формат.

        Args:
            document: DocumentModel.
            format: Целевой формат.

        Returns:
            RenderResult.
        """
        renderer = self.get_renderer(format)
        return await renderer.render(document)