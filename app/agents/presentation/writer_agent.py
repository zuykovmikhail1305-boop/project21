"""Writer Agent — генерирует контент для отдельных слайдов.

Вызывается для КАЖДОГО слайда отдельно. Каждый вызов — простая задача:
написать контент для одного слайда на основе SlideOutline и ResearchResult.

Использует with_structured_output(Slide) — Pydantic валидирует ответ LLM.
При ошибке валидации — retry, затем exception.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.presentation.base import BasePresentationAgent
from app.agents.presentation.models import (
    ResearchResult,
    Slide,
    SlideBlock,
    SlideBlockType,
    SlideOutline,
)

logger = logging.getLogger(__name__)

WRITER_PROMPT = """Ты — копирайтер корпоративных презентаций. Твоя задача — написать контент для слайда.

## Информация о слайде
- Заголовок: {slide_title}
- Тип слайда: {slide_type}
- Цель слайда: {slide_goal}
- Предлагаемый layout: {suggested_layout}

## Контекст из документов
{research_context}

## Ключевые факты
{key_facts}

## Статистика
{statistics}

## Правила написания контента
1. Пиши на русском языке, деловым стилем
2. Будь конкретным — используй цифры и факты из контекста
3. Не более 5-7 блоков на слайд
4. Каждый блок должен быть информативным
5. Минимум 1 блок на слайд (обычно heading + paragraph)

## Доступные типы блоков и их обязательные поля
- heading — заголовок (обязательно: text, level=1-3)
- paragraph — абзац (обязательно: text)
- bullet_list — маркированный список (обязательно: items — список строк)
- chart — график (обязательно: description, опционально: data_source)
- table — таблица (обязательно: headers — список строк, rows — список списков строк)
- quote — цитата (обязательно: text, опционально: source)
- callout — выделенный блок (обязательно: text, опционально: style=info|warning|tip)
- code — блок кода (обязательно: code, опционально: language)
- image — изображение (обязательно: url, опционально: alt)

ВАЖНО: Каждый блок ОБЯЗАН иметь заполненные поля согласно типу.
Например, для paragraph нужно указать text, для bullet_list — items.
Не оставляй поля пустыми!
"""

# Дополнительный промпт для retry — передаёт ошибку валидации из первой попытки
WRITER_RETRY_PROMPT = """Ты — копирайтер корпоративных презентаций. Твоя задача — написать контент для слайда.

## Информация о слайде
- Заголовок: {slide_title}
- Тип слайда: {slide_type}
- Цель слайда: {slide_goal}
- Предлагаемый layout: {suggested_layout}

## Контекст из документов
{research_context}

## Ключевые факты
{key_facts}

## Статистика
{statistics}

## Правила написания контента
1. Пиши на русском языке, деловым стилем
2. Будь конкретным — используй цифры и факты из контекста
3. Не более 5-7 блоков на слайд
4. Каждый блок должен быть информативным
5. Минимум 1 блок на слайд (обычно heading + paragraph)

## Доступные типы блоков и их обязательные поля
- heading — заголовок (обязательно: text, level=1-3)
- paragraph — абзац (обязательно: text)
- bullet_list — маркированный список (обязательно: items — список строк)
- chart — график (обязательно: description, опционально: data_source)
- table — таблица (обязательно: headers — список строк, rows — список списков строк)
- quote — цитата (обязательно: text, опционально: source)
- callout — выделенный блок (обязательно: text, опционально: style=info|warning|tip)
- code — блок кода (обязательно: code, опционально: language)
- image — изображение (обязательно: url, опционально: alt)

## Ошибка предыдущей попытки
{last_error_text}

ВАЖНО: Исправь ошибку из предыдущей попытки. Убедись, что все обязательные поля заполнены.
"""


class WriterError(Exception):
    """Ошибка генерации слайда WriterAgent."""
    pass


class WriterAgent(BasePresentationAgent):
    """Агент для генерации контента одного слайда.

    Использует with_structured_output(Slide) — Pydantic валидирует ответ.
    При ошибке — retry с передачей ошибки валидации в промпт, затем WriterError.
    """

    def __init__(self) -> None:
        super().__init__()
        self._chain = self._build_structured_chain(WRITER_PROMPT, Slide)
        self._retry_chain = self._build_structured_chain(WRITER_RETRY_PROMPT, Slide)

    async def write_slide(
        self,
        slide_outline: SlideOutline,
        research: ResearchResult,
        slide_index: int,
    ) -> Slide:
        """Написать контент для одного слайда.

        Args:
            slide_outline: Описание слайда из PlannerAgent.
            research: Результат ResearchAgent (факты, статистика).
            slide_index: Индекс слайда в презентации.

        Returns:
            Slide с заполненными блоками.

        Raises:
            WriterError: Если LLM недоступен или оба retry не удались.
        """
        if self._chain is None or self._retry_chain is None:
            raise WriterError("WriterAgent: LLM not available")

        # Форматируем контекст
        research_context = research.summary or "Нет контекста"
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
                    "WriterAgent: writing slide %d '%s' (attempt %d/2)",
                    slide_index, slide_outline.title, attempt + 1,
                )

                # Выбираем цепочку: первая попытка — обычная, вторая — с ошибкой
                if attempt == 0:
                    slide = await self._chain.ainvoke({
                        "slide_title": slide_outline.title,
                        "slide_type": slide_outline.slide_type,
                        "slide_goal": slide_outline.goal,
                        "suggested_layout": slide_outline.suggested_layout,
                        "research_context": research_context,
                        "key_facts": key_facts,
                        "statistics": statistics,
                        "input": f"Напиши контент для слайда '{slide_outline.title}'",
                    })
                else:
                    # Передаём ошибку из первой попытки во вторую
                    last_error_text = str(last_error) if last_error else "Неизвестная ошибка"
                    slide = await self._retry_chain.ainvoke({
                        "slide_title": slide_outline.title,
                        "slide_type": slide_outline.slide_type,
                        "slide_goal": slide_outline.goal,
                        "suggested_layout": slide_outline.suggested_layout,
                        "research_context": research_context,
                        "key_facts": key_facts,
                        "statistics": statistics,
                        "last_error_text": last_error_text,
                        "input": f"Исправь ошибку и напиши контент для слайда '{slide_outline.title}'",
                    })

                # with_structured_output уже вернул Slide — валидация прошла
                # Но нужно установить slide_index (LLM может ошибиться)
                slide.slide_index = slide_index

                logger.info(
                    "WriterAgent: slide %d generated with %d blocks",
                    slide_index, len(slide.blocks),
                )
                return slide

            except Exception as e:
                last_error = e
                logger.warning(
                    "WriterAgent: attempt %d/2 failed for slide %d: %s",
                    attempt + 1, slide_index, e,
                )

        # Обе попытки не удались
        raise WriterError(
            f"WriterAgent: failed to generate slide {slide_index} "
            f"('{slide_outline.title}') after 2 attempts: {last_error}"
        )