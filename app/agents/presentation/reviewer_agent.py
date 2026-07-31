"""Reviewer Agent — проверяет качество презентации до рендера.

Проверяет структурное представление слайдов (Slide с блоками):
- Слишком длинные bullet points
- Отсутствие источников
- Отсутствие ключевой мысли
- Повтор информации
- Перегруженный слайд
- Отсутствие выводов

Использует with_structured_output(ReviewResult) — Pydantic валидирует ответ.
При ошибке валидации — retry, затем rule-based fallback.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.presentation.base import BasePresentationAgent
from app.agents.presentation.models import (
    PresentationOutline,
    ReviewIssue,
    ReviewResult,
    Slide,
)

logger = logging.getLogger(__name__)

REVIEWER_PROMPT = """Ты — редактор корпоративных презентаций. Твоя задача — проверить качество презентации и найти проблемы.

## Структура презентации
{outline_summary}

## Слайды
{slides_content}

## Что проверять
1. **content** — достаточно ли контента на каждом слайде? Нет ли пустых слайдов?
2. **structure** — правильная ли структура? Есть ли титульный слайд и заключение?
3. **data** — достаточно ли цифр и фактов? Нет ли голословных утверждений?
4. **consistency** — согласованы ли слайды между собой? Нет ли повторов?
5. **design** — подходят ли типы блоков для цели слайда?

## Критерии оценки
- critical — проблема делает слайд непригодным (пустой слайд, нет заголовка)
- warning — проблема снижает качество (слишком много текста, нет источников)
- suggestion — рекомендация по улучшению
"""


class ReviewerAgent(BasePresentationAgent):
    """Агент для проверки качества презентации.

    Анализирует структурное представление слайдов ДО рендера.
    Использует with_structured_output(ReviewResult).
    """

    def __init__(self) -> None:
        super().__init__()
        self._chain = self._build_structured_chain(REVIEWER_PROMPT, ReviewResult)

    async def review(
        self,
        slides: list[Slide],
        outline: PresentationOutline,
    ) -> ReviewResult:
        """Проверить качество презентации.

        Args:
            slides: Сгенерированные слайды.
            outline: План презентации.

        Returns:
            ReviewResult с найденными проблемами.
        """
        if not slides:
            return ReviewResult(
                needs_revision=True,
                overall_score=0.0,
                summary="Презентация пуста",
                issues=[
                    ReviewIssue(
                        severity="critical",
                        category="content",
                        description="Нет ни одного слайда",
                        fix_suggestion="Запустить генерацию слайдов",
                    ),
                ],
            )

        if self._chain is None:
            logger.error("ReviewerAgent: LLM not available")
            return self._rule_based_review(slides, outline)

        # Форматируем слайды для LLM
        outline_summary = (
            f"Заголовок: {outline.title}\n"
            f"Всего слайдов: {outline.total_slides}\n"
            f"Нарратив: {outline.narrative_flow}\n"
        )
        slides_content = self._format_slides_for_review(slides)

        # Retry loop: 2 попытки
        last_error = None
        for attempt in range(2):
            try:
                logger.info(
                    "ReviewerAgent: reviewing %d slides (attempt %d/2)",
                    len(slides), attempt + 1,
                )
                result = await self._chain.ainvoke({
                    "outline_summary": outline_summary,
                    "slides_content": slides_content,
                    "input": f"Проверь качество презентации '{outline.title}'",
                })
                logger.info(
                    "ReviewerAgent: score=%.2f, needs_revision=%s, issues=%d",
                    result.overall_score, result.needs_revision, len(result.issues),
                )
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "ReviewerAgent: attempt %d/2 failed: %s",
                    attempt + 1, e,
                )

        logger.error("ReviewerAgent: both LLM attempts failed, using rule-based: %s", last_error)
        return self._rule_based_review(slides, outline)

    def _format_slides_for_review(self, slides: list[Slide]) -> str:
        """Форматировать слайды для передачи в LLM."""
        parts = []
        for slide in slides:
            blocks_text = []
            for block in slide.blocks:
                if block.type.value == "heading":
                    level = block.level or 1
                    text = block.text or ""
                    blocks_text.append(f"{'#' * level} {text}")
                elif block.type.value == "paragraph":
                    blocks_text.append(block.text or "")
                elif block.type.value == "bullet_list":
                    items = block.items or []
                    for item in items:
                        blocks_text.append(f"- {item}")
                elif block.type.value == "chart":
                    blocks_text.append(f"[График: {block.description or ''}]")
                elif block.type.value == "table":
                    blocks_text.append(f"[Таблица: {block.headers or []}]")
                else:
                    blocks_text.append(f"[{block.type.value}: text={block.text or ''}]")

            parts.append(
                f"--- Слайд {slide.slide_index + 1} ---\n"
                f"Заголовок: {slide.title}\n"
                f"Ключевая мысль: {slide.key_message}\n"
                f"Контент:\n" + "\n".join(blocks_text)
            )
        return "\n\n".join(parts)

    def _rule_based_review(self, slides: list[Slide], outline: PresentationOutline) -> ReviewResult:
        """Проверка на основе правил (fallback если LLM недоступен)."""
        issues: list[ReviewIssue] = []

        # Проверка 1: есть ли титульный слайд
        if not slides or slides[0].slide_index != 0:
            issues.append(ReviewIssue(
                severity="warning",
                slide_index=0,
                category="structure",
                description="Нет титульного слайда",
                fix_suggestion="Добавить титульный слайд",
            ))

        # Проверка 2: есть ли слайд с выводами
        has_summary = any("вывод" in s.key_message.lower() for s in slides if s.key_message)
        if not has_summary:
            issues.append(ReviewIssue(
                severity="warning",
                category="structure",
                description="Нет слайда с выводами",
                fix_suggestion="Добавить слайд 'Заключение' в конец презентации",
            ))

        # Проверка 3: пустые слайды
        for i, slide in enumerate(slides):
            if not slide.blocks:
                issues.append(ReviewIssue(
                    severity="critical",
                    slide_index=i,
                    category="content",
                    description=f"Слайд {i+1} ('{slide.title}') не содержит блоков",
                    fix_suggestion="Заполнить слайд контентом",
                ))

        # Проверка 4: слишком много блоков на слайде
        for i, slide in enumerate(slides):
            if len(slide.blocks) > 8:
                issues.append(ReviewIssue(
                    severity="warning",
                    slide_index=i,
                    category="design",
                    description=f"Слайд {i+1} ('{slide.title}') перегружен ({len(slide.blocks)} блоков)",
                    fix_suggestion="Разбить на несколько слайдов или сократить контент",
                ))

        needs_revision = any(i.severity == "critical" for i in issues)
        score = max(0.0, 1.0 - (len(issues) * 0.15))

        return ReviewResult(
            needs_revision=needs_revision,
            issues=issues,
            overall_score=score,
            summary=f"Найдено {len(issues)} проблем: {sum(1 for i in issues if i.severity == 'critical')} critical, "
                    f"{sum(1 for i in issues if i.severity == 'warning')} warning",
        )