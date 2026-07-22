"""Marp Renderer: конвертация Marp-совместимого Markdown в PDF/PPTX/HTML.

Использует Marp CLI (@marp-team/marp-cli) для рендеринга.
Требует установленного Node.js и Marp CLI.
"""

import logging
import os
import subprocess
import uuid
from typing import Optional

from app.services.artifact.base import RenderResult

logger = logging.getLogger(__name__)


class MarpRenderer:
    """Renderer using Marp CLI for Markdown → PDF/PPTX/HTML.

    Поддерживаемые форматы:
    - pdf: marp --pdf input.md -o output.pdf
    - pptx: marp --pptx input.md -o output.pptx
    - html: marp --html input.md -o output.html
    """

    SUPPORTED_FORMATS = {
        "pdf": "--pdf",
        "pptx": "--pptx",
        "html": "--html",
    }

    MIME_TYPES = {
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "html": "text/html",
    }

    def __init__(self, output_dir: str = "/tmp/artifacts", marp_bin: str = "marp"):
        self.output_dir = output_dir
        self.marp_bin = marp_bin
        os.makedirs(output_dir, exist_ok=True)
        self._marp_available = self._check_marp()

    def _check_marp(self) -> bool:
        """Проверить доступность Marp CLI."""
        try:
            result = subprocess.run(
                [self.marp_bin, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                logger.info(f"Marp CLI available: {result.stdout.strip()}")
                return True
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Marp CLI not found. Install with: npm install -g @marp-team/marp-cli")
            return False

    def render(self, markdown_content: str, output_format: str) -> RenderResult:
        """Render Marp markdown to target format.

        Args:
            markdown_content: Marp-совместимый Markdown контент.
            output_format: Целевой формат: pdf, pptx, html.

        Returns:
            RenderResult с путём к сгенерированному файлу.
        """
        if output_format not in self.SUPPORTED_FORMATS:
            return RenderResult(
                success=False,
                error=f"Unsupported format: {output_format}. "
                      f"Supported: {', '.join(self.SUPPORTED_FORMATS.keys())}",
            )

        if not self._marp_available:
            return RenderResult(
                success=False,
                error="Marp CLI не установлен. Установите: npm install -g @marp-team/marp-cli",
            )

        # Сохраняем Markdown во временный файл
        file_id = uuid.uuid4().hex[:12]
        md_path = os.path.join(self.output_dir, f"artifact_{file_id}.md")
        output_path = os.path.join(self.output_dir, f"artifact_{file_id}.{output_format}")

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            # Запускаем Marp CLI
            result = subprocess.run(
                [
                    self.marp_bin,
                    self.SUPPORTED_FORMATS[output_format],
                    md_path,
                    "-o", output_path,
                    "--allow-local-files",  # разрешаем локальные пути к графикам
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                error_msg = result.stderr[:2000] if result.stderr else "Unknown Marp error"
                logger.error(f"Marp render failed: {error_msg}")
                return RenderResult(success=False, error=error_msg)

            # Проверяем, что файл создан
            if not os.path.exists(output_path):
                return RenderResult(
                    success=False,
                    error=f"Marp не создал выходной файл: {output_path}",
                )

            file_size = os.path.getsize(output_path)
            logger.info(
                f"Marp rendered {output_format}: {output_path} ({file_size} bytes)"
            )

            return RenderResult(
                success=True,
                file_path=output_path,
                file_size=file_size,
                mime_type=self.MIME_TYPES.get(output_format, "application/octet-stream"),
            )

        except subprocess.TimeoutExpired:
            return RenderResult(success=False, error="Marp render timed out (60s)")
        except Exception as e:
            logger.exception("Marp render error")
            return RenderResult(success=False, error=str(e))
        finally:
            # Очищаем временный .md файл
            try:
                os.unlink(md_path)
            except OSError:
                pass