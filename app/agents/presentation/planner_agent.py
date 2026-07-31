"""Planner Agent — проектирует структуру презентации (outline).

Planner НЕ пишет текст. Он определяет:
- Сколько слайдов
- Какой тип каждого слайда
- Какова цель каждого слайда
- Какие данные нужны для каждого слайда

Вход: IntentResult + ResearchResult
Выход: PresentationOutline (список SlideOutline)

Использует with_structured_output(PresentationOutline) — Pydantic валидирует ответ.
При ошибке валидации — retry, затем fallback outline.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.presentation.base import BasePresentationAgent
from app.agents.presentation.models import (
    IntentResult,
    PresentationOutline,
    ResearchResult,
    SlideOutline,
)

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """Ты — архитектор презентаций. Твоя задача — спроектировать структуру презентации.

## Цель презентации
{goal_summary}

## Контекст из документов
{research_summary}

## Ключевые факты
{key_facts}

## Статистика
{statistics}

## Что нужно сделать
Спроектируй структуру презентации — ТОЛЬКО outline, без написания контента.

Для каждого слайда определи:
1. **title** — заголовок слайда
2. **slide_type** — тип слайда:
   - title — титульный слайд
   - content — контентный слайд
   - section_divider — разделитель разделов
   - data — слайд с данными/цифрами
   - comparison — сравнение
   - summary — слайд-резюме
3. **goal** — что этот слайд должен коммуницировать (одно предложение)
4. **required_data** — какие факты или статистику использовать (ссылки из контекста)
5. **suggested_layout** — предлагаемый layout:
   - title_only — только заголовок
   - bullets — маркированный список
   - chart — график/диаграмма
   - two_column — две колонки
   - quote — цитата
   - comparison — сравнение

## Правила
- Не более 15 слайдов
- Первый слайд — титульный (title)
- Последний слайд — summary с выводами
- Каждый слайд должен иметь чёткую цель
- Используй разнообразные типы слайдов
"""


class PlannerAgent(BasePresentationAgent):
    """Агент для проектирования структуры презентации.

    Создаёт PresentationOutline — список слайдов с типами и целями.
    НЕ генерирует контент — только структуру.

    Использует with_structured_output(PresentationOutline) — Pydantic валидирует ответ.
    При ошибке — retry (2 попытки), затем fallback outline.
    """

    def __init__(self) -> None:
        super().__init__()
        self._chain = self._build_structured_chain(PLANNER_PROMPT, PresentationOutline)

    async def plan(
        self,
        intent: IntentResult,
        research: ResearchResult,
    ) -> PresentationOutline:
        """Спроектировать структуру презентации.

        Args:
            intent: Результат IntentAgent (цель, аудитория, темы).
            research: Результат ResearchAgent (факты, статистика).

        Returns:
            PresentationOutline со списком слайдов.
        """
        if self._chain is None:
            logger.error("PlannerAgent: LLM not available")
            return self._fallback_outline(intent)

        # Форматируем входные данные
        goal_summary = (
            f"Заголовок: {intent.title}\n"
            f"Цель: {intent.goal}\n"
            f"Аудитория: {intent.audience}\n"
            f"Тональность: {intent.tone}\n"
            f"Темы: {', '.join(intent.key_topics)}\n"
            f"Ограничения: {', '.join(intent.constraints) if intent.constraints else 'нет'}"
        )
        research_summary = research.summary or "Нет контекста"
        key_facts = "\n".join(f"- {f}" for f in research.key_facts) if research.key_facts else "Нет фактов"
        statistics = "\n".join(
            f"- {s.get('metric', '?')}: {s.get('value', '?')} ({s.get('period', '?')})"
            for s in research.statistics
        ) if research.statistics else "Нет статистики"

        # Retry loop: 2 попытки
        last_error = None
        for attempt in range(2):
            try:
                logger.info(
                    "PlannerAgent: planning for '%s' (attempt %d/2)",
                    intent.title, attempt + 1,
                )
                outline = await self._chain.ainvoke({
                    "goal_summary": goal_summary,
                    "research_summary": research_summary,
                    "key_facts": key_facts,
                    "statistics": statistics,
                    "input": f"Спроектируй структуру презентации для '{intent.title}'",
                })

                # with_structured_output уже вернул PresentationOutline — валидация прошла
                logger.info(
                    "PlannerAgent: planned %d slides, flow=%s",
                    outline.total_slides, outline.narrative_flow,
                )
                return outline

            except Exception as e:
                last_error = e
                logger.warning(
                    "PlannerAgent: attempt %d/2 failed: %s",
                    attempt + 1, e,
                )

        # Обе попытки не удались — fallback
        logger.error("PlannerAgent: both attempts failed, using fallback: %s", last_error)
        return self._fallback_outline(intent)

    def _fallback_outline(self, intent: IntentResult) -> PresentationOutline:
        """Создать базовый outline если LLM недоступен или все retry не удались."""
        slides = [
            SlideOutline(title=intent.title, slide_type="title", goal="Представить тему"),
            SlideOutline(title="Обзор", slide_type="content", goal="Обзор ключевых аспектов"),
            SlideOutline(title="Основные показатели", slide_type="data", goal="Показать ключевые метрики"),
            SlideOutline(title="Анализ", slide_type="content", goal="Проанализировать данные"),
            SlideOutline(title="Заключение", slide_type="summary", goal="Подвести итоги"),
        ]
        return PresentationOutline(
            title=intent.title,
            total_slides=len(slides),
            narrative_flow="topical",
            slides=slides,
        )