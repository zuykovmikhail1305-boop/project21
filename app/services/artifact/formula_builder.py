"""FormulaBuilder: LaTeX → SVG/PNG.

Конвертирует LaTeX-формулы в изображения для вставки в документы.
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


class FormulaBuilder:
    """Построение формул: LaTeX → SVG/PNG."""

    def __init__(self, output_dir: str = "/tmp/artifacts/assets/formula"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    async def build(
        self,
        ref: AssetReference,
        theme: Theme,
    ) -> ArtifactAsset:
        """Построить формулу из LaTeX.

        Args:
            ref: Ссылка на ассет с spec: {latex}.
            theme: Тема оформления.

        Returns:
            ArtifactAsset с путём к SVG/PNG.
        """
        latex = ref.spec.get("latex", "")

        if not latex:
            raise ValueError("Empty LaTeX formula")

        # Пробуем через MathJax (node.js) или pdflatex
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_formula.svg")

        # Способ 1: MathJax (node.js)
        if await self._try_mathjax(latex, file_path):
            pass
        # Способ 2: pdflatex + pdf2svg
        elif await self._try_pdflatex(latex, file_path):
            pass
        # Способ 3: placeholder SVG
        else:
            file_path = self._create_placeholder_svg(ref, latex)

        file_size = os.path.getsize(file_path)
        logger.info("Formula built: id=%s size=%d", ref.asset_id, file_size)

        return ArtifactAsset(
            asset_id=ref.asset_id,
            asset_type=AssetType.FORMULA,
            name=f"{ref.asset_id}_formula.svg",
            mime_type="image/svg+xml",
            file_path=file_path,
            metadata={"latex": latex[:100]},
            size_bytes=file_size,
        )

    async def _try_mathjax(self, latex: str, output_path: str) -> bool:
        """Попробовать сконвертировать через MathJax (node.js)."""
        try:
            script = f"""
const mj = require('mathjax-node');
mj.config({{
  MathJax: {{
    loader: {{load: ['input/TeX', 'output/SVG']}},
  }},
}});
mj.start();
mj.typeset({{
  math: {repr(latex)},
  format: 'TeX',
  svg: true,
}}, function (data) {{
  if (data.errors) {{
    console.error(data.errors);
    process.exit(1);
  }}
  process.stdout.write(data.svg);
}});
"""
            result = subprocess.run(
                ["node", "-e", script],
                capture_output=True, text=True, timeout=15,
            )

            if result.returncode == 0 and result.stdout:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("MathJax not available: %s", e)

        return False

    async def _try_pdflatex(self, latex: str, output_path: str) -> bool:
        """Попробовать сконвертировать через pdflatex + pdf2svg."""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tex_content = f"""\\documentclass[preview]{{standalone}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\begin{{document}}
${latex}$
\\end{{document}}
"""
                tex_path = os.path.join(tmpdir, "formula.tex")
                with open(tex_path, "w", encoding="utf-8") as f:
                    f.write(tex_content)

                # pdflatex
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, tex_path],
                    capture_output=True, text=True, timeout=30,
                )

                pdf_path = os.path.join(tmpdir, "formula.pdf")
                if not os.path.exists(pdf_path):
                    return False

                # pdf2svg
                result = subprocess.run(
                    ["pdf2svg", pdf_path, output_path],
                    capture_output=True, text=True, timeout=15,
                )

                return result.returncode == 0 and os.path.exists(output_path)

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("pdflatex/pdf2svg not available: %s", e)

        return False

    def _create_placeholder_svg(self, ref: AssetReference, latex: str) -> str:
        """Создать placeholder SVG с LaTeX-кодом."""
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_formula.svg")

        # Экранируем для SVG
        safe_latex = latex.replace("&", "&").replace("<", "<").replace(">", ">")

        svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="400" height="80">
  <rect width="400" height="80" fill="#f8f9fa" rx="8"/>
  <text x="200" y="35" text-anchor="middle" font-family="Arial" font-size="14" fill="#172B4D">
    LaTeX Formula
  </text>
  <text x="200" y="60" text-anchor="middle" font-family="monospace" font-size="11" fill="#7A869A">
    {safe_latex}
  </text>
</svg>"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        return file_path


def repr(s: str) -> str:
    """Безопасное repr для JavaScript."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"