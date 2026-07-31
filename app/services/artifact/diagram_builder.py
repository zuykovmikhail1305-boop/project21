"""DiagramBuilder: Mermaid/PlantUML/DrawIO → SVG.

Без LLM. Конвертирует текстовое описание диаграммы в SVG/PNG.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Optional

from app.services.artifact.models import (
    ArtifactAsset,
    AssetReference,
    AssetType,
    Theme,
)

logger = logging.getLogger(__name__)


class DiagramBuilder:
    """Построение диаграмм: Mermaid → SVG."""

    def __init__(self, output_dir: str = "/tmp/artifacts/assets/diagram"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    async def build(
        self,
        ref: AssetReference,
        theme: Theme,
    ) -> ArtifactAsset:
        """Построить диаграмму.

        Args:
            ref: Ссылка на ассет с spec: {engine, code}.
            theme: Тема оформления.

        Returns:
            ArtifactAsset с путём к SVG/PNG.
        """
        engine = ref.spec.get("engine", "mermaid")
        code = ref.spec.get("code", "")

        if engine == "mermaid":
            return await self._build_mermaid(ref, code, theme)
        elif engine == "plantuml":
            return await self._build_plantuml(ref, code, theme)
        elif engine == "drawio":
            return await self._build_drawio(ref, code, theme)
        else:
            raise ValueError(f"Unsupported diagram engine: {engine}")

    async def _build_mermaid(
        self,
        ref: AssetReference,
        code: str,
        theme: Theme,
    ) -> ArtifactAsset:
        """Mermaid → SVG через CLI (mmdc)."""
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_diagram.svg")

        # Пробуем через mmdc (Mermaid CLI)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mmd", delete=False
            ) as f:
                f.write(code)
                mmd_path = f.name

            result = subprocess.run(
                ["mmdc", "-i", mmd_path, "-o", file_path, "-b", "transparent"],
                capture_output=True, text=True, timeout=30,
            )

            os.unlink(mmd_path)

            if result.returncode == 0 and os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                logger.info("Mermaid diagram built: %s (%d bytes)", file_path, file_size)
                return ArtifactAsset(
                    asset_id=ref.asset_id,
                    asset_type=AssetType.DIAGRAM,
                    name=f"{ref.asset_id}_diagram.svg",
                    mime_type="image/svg+xml",
                    file_path=file_path,
                    metadata={"engine": "mermaid"},
                    size_bytes=file_size,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("Mermaid CLI not available, falling back to placeholder: %s", e)

        # Fallback: создаём placeholder SVG
        return self._create_placeholder_svg(ref, code, "mermaid")

    async def _build_plantuml(
        self,
        ref: AssetReference,
        code: str,
        theme: Theme,
    ) -> ArtifactAsset:
        """PlantUML → PNG через CLI."""
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_diagram.png")

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".puml", delete=False
            ) as f:
                f.write(code)
                puml_path = f.name

            result = subprocess.run(
                ["plantuml", "-tpng", puml_path, "-o", self.output_dir],
                capture_output=True, text=True, timeout=30,
            )

            os.unlink(puml_path)

            # PlantUML сохраняет в ту же директорию с именем файла
            expected = os.path.join(
                self.output_dir,
                os.path.splitext(os.path.basename(puml_path))[0] + ".png",
            )
            if os.path.exists(expected):
                os.rename(expected, file_path)
                file_size = os.path.getsize(file_path)
                return ArtifactAsset(
                    asset_id=ref.asset_id,
                    asset_type=AssetType.DIAGRAM,
                    name=f"{ref.asset_id}_diagram.png",
                    mime_type="image/png",
                    file_path=file_path,
                    metadata={"engine": "plantuml"},
                    size_bytes=file_size,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("PlantUML CLI not available: %s", e)

        return self._create_placeholder_svg(ref, code, "plantuml")

    async def _build_drawio(
        self,
        ref: AssetReference,
        code: str,
        theme: Theme,
    ) -> ArtifactAsset:
        """DrawIO → PNG/SVG через CLI."""
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_diagram.png")

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".drawio", delete=False
            ) as f:
                f.write(code)
                drawio_path = f.name

            result = subprocess.run(
                ["drawio", "--export", "--format", "png", "--output", file_path, drawio_path],
                capture_output=True, text=True, timeout=30,
            )

            os.unlink(drawio_path)

            if result.returncode == 0 and os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                return ArtifactAsset(
                    asset_id=ref.asset_id,
                    asset_type=AssetType.DIAGRAM,
                    name=f"{ref.asset_id}_diagram.png",
                    mime_type="image/png",
                    file_path=file_path,
                    metadata={"engine": "drawio"},
                    size_bytes=file_size,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("DrawIO CLI not available: %s", e)

        return self._create_placeholder_svg(ref, code, "drawio")

    def _create_placeholder_svg(
        self,
        ref: AssetReference,
        code: str,
        engine: str,
    ) -> ArtifactAsset:
        """Создать placeholder SVG, если CLI недоступен."""
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_diagram.svg")

        svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400">
  <rect width="600" height="400" fill="#f8f9fa" rx="8"/>
  <text x="300" y="40" text-anchor="middle" font-family="Arial" font-size="16" fill="#172B4D">
    {engine.upper()} Diagram
  </text>
  <text x="300" y="70" text-anchor="middle" font-family="Arial" font-size="12" fill="#7A869A">
    ID: {ref.asset_id}
  </text>
  <line x1="50" y1="90" x2="550" y2="90" stroke="#ddd" stroke-width="1"/>
  <text x="300" y="200" text-anchor="middle" font-family="monospace" font-size="10" fill="#666">
    Install {engine} CLI to render actual diagrams
  </text>
  <text x="300" y="380" text-anchor="middle" font-family="Arial" font-size="10" fill="#999">
    Placeholder — generated by Artifact System v2
  </text>
</svg>"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        file_size = os.path.getsize(file_path)
        logger.info("Placeholder diagram created: %s", file_path)

        return ArtifactAsset(
            asset_id=ref.asset_id,
            asset_type=AssetType.DIAGRAM,
            name=f"{ref.asset_id}_diagram.svg",
            mime_type="image/svg+xml",
            file_path=file_path,
            metadata={"engine": engine, "placeholder": True},
            size_bytes=file_size,
        )