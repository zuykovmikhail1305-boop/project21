"""Двухуровневый Validator для артефактов.

Level 1: DocumentValidator — проверка структуры документа до рендеринга.
Level 2: RenderValidator — проверка выходного файла после рендеринга.
Auto-fix для простых ошибок.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from app.services.artifact.models import (
    BlockType,
    CheckResult,
    DocumentModel,
    RenderResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ============================================================
# Level 1: DocumentValidator
# ============================================================


class DocumentValidator:
    """Уровень 1: проверка структуры документа до рендеринга.

    Проверяет:
    1. required_fields — обязательные поля заполнены
    2. empty_blocks — нет пустых блоков
    3. asset_refs — все asset_refs имеют matching AssetReference
    4. section_structure — структура секций валидна
    5. block_types — типы блоков корректны
    """

    async def validate(self, document: DocumentModel) -> ValidationResult:
        """Запустить все проверки документа."""
        result = ValidationResult(passed=True)

        result.add_check(await self._check_required_fields(document))
        result.add_check(await self._check_empty_blocks(document))
        result.add_check(await self._check_asset_refs(document))
        result.add_check(await self._check_section_structure(document))
        result.add_check(await self._check_block_types(document))

        return result

    async def _check_required_fields(self, document: DocumentModel) -> CheckResult:
        """Проверка 1: обязательные поля."""
        errors = []

        if not document.title:
            errors.append("title is empty")
        if not document.artifact_type:
            errors.append("artifact_type is empty")
        if not document.sections:
            errors.append("no sections defined")

        if errors:
            return CheckResult(
                check_name="required_fields",
                passed=False,
                message="Missing required fields: " + "; ".join(errors),
            )
        return CheckResult(
            check_name="required_fields",
            passed=True,
            message="All required fields present",
        )

    async def _check_empty_blocks(self, document: DocumentModel) -> CheckResult:
        """Проверка 2: нет пустых блоков."""
        empty_blocks = []

        for section in document.sections:
            for block in section.blocks:
                if self._is_block_empty(block):
                    empty_blocks.append(
                        f"section={section.id} block={block.id} type={block.block_type.value}"
                    )

        if empty_blocks:
            return CheckResult(
                check_name="empty_blocks",
                passed=False,
                message=f"Found {len(empty_blocks)} empty blocks",
                details={"empty_blocks": empty_blocks},
            )
        return CheckResult(
            check_name="empty_blocks",
            passed=True,
            message="No empty blocks",
        )

    async def _check_asset_refs(self, document: DocumentModel) -> CheckResult:
        """Проверка 3: все asset_refs имеют matching AssetReference."""
        missing_refs = []

        for section in document.sections:
            for block in section.blocks:
                asset_ids = block.get_asset_refs()
                for asset_id in asset_ids:
                    # Проверяем, что AssetReference существует в документе
                    found = False
                    for ref in document.get_all_asset_refs():
                        if ref.asset_id == asset_id:
                            found = True
                            break
                    if not found:
                        missing_refs.append(
                            f"block={block.id} missing asset_ref={asset_id}"
                        )

        if missing_refs:
            return CheckResult(
                check_name="asset_refs",
                passed=False,
                message=f"Found {len(missing_refs)} missing asset references",
                details={"missing_refs": missing_refs},
            )
        return CheckResult(
            check_name="asset_refs",
            passed=True,
            message="All asset references valid",
        )

    async def _check_section_structure(self, document: DocumentModel) -> CheckResult:
        """Проверка 4: структура секций валидна."""
        errors = []

        for i, section in enumerate(document.sections):
            if not section.title:
                errors.append(f"section[{i}] has no title")
            if not section.blocks:
                errors.append(f"section[{i}] ({section.title}) has no blocks")

        if errors:
            return CheckResult(
                check_name="section_structure",
                passed=False,
                message="Section structure issues: " + "; ".join(errors),
            )
        return CheckResult(
            check_name="section_structure",
            passed=True,
            message="Section structure valid",
        )

    async def _check_block_types(self, document: DocumentModel) -> CheckResult:
        """Проверка 5: типы блоков корректны."""
        errors = []

        for section in document.sections:
            for block in section.blocks:
                if not self._is_block_content_valid(block):
                    errors.append(
                        f"section={section.id} block={block.id} type={block.block_type.value} "
                        f"has no content"
                    )

        if errors:
            return CheckResult(
                check_name="block_types",
                passed=False,
                message="Block type issues: " + "; ".join(errors),
                details={"block_errors": errors},
            )
        return CheckResult(
            check_name="block_types",
            passed=True,
            message="All block types valid",
        )

    def _is_block_empty(self, block) -> bool:
        """Проверить, пуст ли блок."""
        if block.block_type == BlockType.HEADING and block.heading:
            return not block.heading.text
        elif block.block_type == BlockType.PARAGRAPH and block.paragraph:
            return not block.paragraph.text
        elif block.block_type == BlockType.TABLE and block.table:
            return not block.table.headers and not block.table.rows
        elif block.block_type == BlockType.CHART and block.chart:
            return not block.chart.description
        elif block.block_type == BlockType.DIAGRAM and block.diagram:
            return not block.diagram.code
        elif block.block_type == BlockType.FORMULA and block.formula:
            return not block.formula.latex
        elif block.block_type == BlockType.CODE and block.code:
            return not block.code.code
        elif block.block_type == BlockType.QUOTE and block.quote:
            return not block.quote.text
        elif block.block_type == BlockType.IMAGE and block.image:
            return not block.image.src
        elif block.block_type == BlockType.BULLET_LIST and block.bullet_list:
            return not block.bullet_list.items
        elif block.block_type == BlockType.COLUMNS and block.columns:
            return not block.columns.columns
        elif block.block_type == BlockType.CALLOUT and block.callout:
            return not block.callout.text
        return True

    def _is_block_content_valid(self, block) -> bool:
        """Проверить, что блок имеет контент соответствующего типа."""
        if block.block_type == BlockType.HEADING:
            return block.heading is not None
        elif block.block_type == BlockType.PARAGRAPH:
            return block.paragraph is not None
        elif block.block_type == BlockType.TABLE:
            return block.table is not None
        elif block.block_type == BlockType.CHART:
            return block.chart is not None
        elif block.block_type == BlockType.DIAGRAM:
            return block.diagram is not None
        elif block.block_type == BlockType.FORMULA:
            return block.formula is not None
        elif block.block_type == BlockType.CODE:
            return block.code is not None
        elif block.block_type == BlockType.QUOTE:
            return block.quote is not None
        elif block.block_type == BlockType.IMAGE:
            return block.image is not None
        elif block.block_type == BlockType.BULLET_LIST:
            return block.bullet_list is not None
        elif block.block_type == BlockType.COLUMNS:
            return block.columns is not None
        elif block.block_type == BlockType.CALLOUT:
            return block.callout is not None
        return False


# ============================================================
# Level 2: RenderValidator
# ============================================================


class RenderValidator:
    """Уровень 2: проверка выходного файла после рендеринга.

    Проверяет:
    1. text_overflow — текст не вылезает за пределы
    2. images_exist — все изображения существуют
    3. links_valid — ссылки не битые
    4. file_size — размер файла в пределах лимита
    5. file_valid — файл не повреждён
    6. slide_count — число слайдов в пределах
    """

    MAX_FILE_SIZE_MB = 50
    MIN_SLIDES = 1
    MAX_SLIDES = 50

    async def validate(self, render_result: RenderResult) -> ValidationResult:
        """Запустить все проверки результата рендеринга."""
        result = ValidationResult(passed=True)

        if not render_result.success or not render_result.file_path:
            result.add_check(CheckResult(
                check_name="render_success",
                passed=False,
                message=f"Render failed: {render_result.error}",
            ))
            return result

        result.add_check(self._check_file_exists(render_result))
        result.add_check(self._check_file_size(render_result))
        result.add_check(self._check_images_exist(render_result))
        result.add_check(self._check_links_valid(render_result))
        result.add_check(self._check_slide_count(render_result))
        result.add_check(self._check_file_valid(render_result))

        return result

    def _check_file_exists(self, render_result: RenderResult) -> CheckResult:
        """Проверка: файл существует."""
        if render_result.file_path and os.path.exists(render_result.file_path):
            return CheckResult(
                check_name="file_exists",
                passed=True,
                message=f"File exists: {render_result.file_path}",
            )
        return CheckResult(
            check_name="file_exists",
            passed=False,
            message=f"File not found: {render_result.file_path}",
        )

    def _check_file_size(self, render_result: RenderResult) -> CheckResult:
        """Проверка: размер файла в пределах лимита."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            return CheckResult(check_name="file_size", passed=False, message="File not found")

        size_mb = os.path.getsize(render_result.file_path) / (1024 * 1024)
        if size_mb <= self.MAX_FILE_SIZE_MB:
            return CheckResult(
                check_name="file_size",
                passed=True,
                message=f"File size OK: {size_mb:.1f}MB (limit: {self.MAX_FILE_SIZE_MB}MB)",
            )
        return CheckResult(
            check_name="file_size",
            passed=False,
            message=f"File too large: {size_mb:.1f}MB (limit: {self.MAX_FILE_SIZE_MB}MB)",
        )

    def _check_images_exist(self, render_result: RenderResult) -> CheckResult:
        """Проверка: все изображения существуют."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            return CheckResult(check_name="images_exist", passed=False, message="File not found")

        try:
            with open(render_result.file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return CheckResult(check_name="images_exist", passed=True, message="Cannot read file (binary)")

        # Ищем все ссылки на изображения
        image_refs = re.findall(r'!\[.*?\]\(([^)]+)\)', content)
        missing = []

        for ref in image_refs:
            # Пропускаем URL
            if ref.startswith(("http://", "https://")):
                continue
            # Проверяем локальный файл
            if not os.path.exists(ref):
                missing.append(ref)

        if missing:
            return CheckResult(
                check_name="images_exist",
                passed=False,
                message=f"Missing {len(missing)} images",
                details={"missing_images": missing},
            )
        return CheckResult(
            check_name="images_exist",
            passed=True,
            message=f"All {len(image_refs)} images found",
        )

    def _check_links_valid(self, render_result: RenderResult) -> CheckResult:
        """Проверка: ссылки не битые (только синтаксис)."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            return CheckResult(check_name="links_valid", passed=False, message="File not found")

        try:
            with open(render_result.file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return CheckResult(check_name="links_valid", passed=True, message="Cannot read file (binary)")

        # Ищем все Markdown-ссылки
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        broken = []

        for text, url in links:
            # Пропускаем изображения
            if not text:
                continue
            # Проверяем синтаксис
            if not url or url.isspace():
                broken.append(f"Link '{text}' has empty URL")

        if broken:
            return CheckResult(
                check_name="links_valid",
                passed=False,
                message=f"Found {len(broken)} broken links",
                details={"broken_links": broken},
            )
        return CheckResult(
            check_name="links_valid",
            passed=True,
            message=f"All {len(links)} links syntactically valid",
        )

    def _check_slide_count(self, render_result: RenderResult) -> CheckResult:
        """Проверка: число слайдов в пределах."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            return CheckResult(check_name="slide_count", passed=False, message="File not found")

        try:
            with open(render_result.file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return CheckResult(check_name="slide_count", passed=True, message="Cannot read file (binary)")

        # Считаем разделители слайдов
        slide_count = content.count("\n---\n") + 1

        if slide_count < self.MIN_SLIDES:
            return CheckResult(
                check_name="slide_count",
                passed=False,
                message=f"Too few slides: {slide_count} (min: {self.MIN_SLIDES})",
            )
        if slide_count > self.MAX_SLIDES:
            return CheckResult(
                check_name="slide_count",
                passed=False,
                message=f"Too many slides: {slide_count} (max: {self.MAX_SLIDES})",
            )
        return CheckResult(
            check_name="slide_count",
            passed=True,
            message=f"Slide count OK: {slide_count}",
        )

    def _check_file_valid(self, render_result: RenderResult) -> CheckResult:
        """Проверка: файл не повреждён."""
        if not render_result.file_path or not os.path.exists(render_result.file_path):
            return CheckResult(check_name="file_valid", passed=False, message="File not found")

        file_size = os.path.getsize(render_result.file_path)
        if file_size == 0:
            return CheckResult(
                check_name="file_valid",
                passed=False,
                message="File is empty (0 bytes)",
            )

        # Проверка по MIME-типу
        mime = render_result.mime_type or ""
        ext = os.path.splitext(render_result.file_path)[1].lower()

        if mime == "application/pdf" or ext == ".pdf":
            # Проверка PDF magic bytes
            with open(render_result.file_path, "rb") as f:
                header = f.read(5)
            if header != b"%PDF-":
                return CheckResult(
                    check_name="file_valid",
                    passed=False,
                    message="File has .pdf extension but is not a valid PDF",
                )

        return CheckResult(
            check_name="file_valid",
            passed=True,
            message=f"File valid: {file_size} bytes, type={mime or ext}",
        )


# ============================================================
# Auto-fix
# ============================================================


class ArtifactAutoFix:
    """Автоматическое исправление простых ошибок в документе."""

    async def fix(self, document: DocumentModel, validation: ValidationResult) -> DocumentModel:
        """Исправить простые ошибки.

        Args:
            document: DocumentModel с ошибками.
            validation: Результат валидации.

        Returns:
            Исправленный DocumentModel.
        """
        for error in validation.errors:
            if error.check_name == "empty_blocks":
                document = self._fix_empty_blocks(document, error)
            elif error.check_name == "section_structure":
                document = self._fix_section_structure(document, error)

        return document

    def _fix_empty_blocks(self, document: DocumentModel, error: CheckResult) -> DocumentModel:
        """Удалить пустые блоки."""
        empty_ids = set()
        details = error.details.get("empty_blocks", [])
        for desc in details:
            # "section=xxx block=yyy type=zzz"
            match = re.search(r"block=(\S+)", desc)
            if match:
                empty_ids.add(match.group(1))

        for section in document.sections:
            section.blocks = [b for b in section.blocks if b.id not in empty_ids]

        logger.info("Auto-fix: removed %d empty blocks", len(empty_ids))
        return document

    def _fix_section_structure(self, document: DocumentModel, error: CheckResult) -> DocumentModel:
        """Исправить структуру секций."""
        # Добавляем заглушки для пустых секций
        for section in document.sections:
            if not section.blocks:
                from app.services.artifact.models import Block, BlockType, ParagraphBlock
                placeholder = Block(
                    block_type=BlockType.PARAGRAPH,
                    paragraph=ParagraphBlock(text="[Content pending]"),
                )
                section.blocks.append(placeholder)
                logger.info("Auto-fix: added placeholder to empty section %s", section.id)

        return document