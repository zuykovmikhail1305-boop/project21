"""Intent Agent — анализирует запрос пользователя и извлекает цель презентации.

Это самый простой агент в пайплайне. Он использует with_structured_output()
с плоской Pydantic-моделью IntentResult, что GigaChat надёжно обрабатывает.

Вход: сырой запрос пользователя (str)
Выход: IntentResult (title, goal, audience, tone, key_topics, constraints)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.presentation.base import BasePresentationAgent
from app.agents.presentation.models import IntentResult

logger = logging.getLogger(__name__)

INTENT_PROMPT = """Ты — аналитик презентаций. Твоя задача — проанализировать запрос пользователя и определить цель, аудиторию и структуру будущей презентации.

## Что нужно определить
1. **Заголовок презентации** — краткий, информативный заголовок на русском
2. **Цель** — зачем нужна презентация:
   - inform — проинформировать
   - persuade — убедить
   - educate — обучить
   - report — отчитаться
3. **Аудитория** — для кого презентация:
   - investors — инвесторы
   - management — руководство
   - team — команда
   - general — широкая аудитория
4. **Тональность** — стиль изложения:
   - formal — официально-деловой
   - neutral — нейтральный
   - casual — неформальный
5. **Ключевые темы** — 3-5 основных тем для раскрытия
6. **Ограничения** — если пользователь указал (макс слайдов, формат и т.д.)
7. **Рекомендуемое количество слайдов** — 5-15, в зависимости от сложности темы

## Пример
Запрос: "сделай презентацию о выручке Ozon для инвесторов"
Ответ:
- title: "Выручка Ozon: анализ и прогнозы"
- goal: "inform"
- audience: "investors"
- tone: "formal"
- key_topics: ["Обзор компании Ozon", "Динамика выручки", "Факторы роста", "Прогнозы"]
- constraints: []
- suggested_slide_count: 10
"""


class IntentAgent(BasePresentationAgent):
    """Агент для извлечения цели презентации из запроса пользователя.

    Использует with_structured_output(IntentResult) — плоская модель,
    которую GigaChat надёжно обрабатывает.
    """

    def __init__(self) -> None:
        super().__init__()
        self._chain = self._build_structured_chain(INTENT_PROMPT, IntentResult)

    async def analyze(self, query: str) -> IntentResult:
        """Проанализировать запрос и извлечь цель презентации.

        Args:
            query: Сырой запрос пользователя.

        Returns:
            IntentResult с целью, аудиторией, тональностью и темами.

        Raises:
            RuntimeError: Если LLM недоступен или произошла ошибка.
        """
        if self._chain is None:
            logger.error("IntentAgent: LLM not available")
            return IntentResult(
                title=query[:100],
                goal="inform",
                audience="general",
                tone="neutral",
                key_topics=[query[:200]],
                suggested_slide_count=8,
            )

        try:
            logger.info("IntentAgent: analyzing query='%s'", query[:100])
            result = await self._chain.ainvoke({"query": query, "input": query})
            logger.info(
                "IntentAgent: result title='%s', goal=%s, audience=%s, topics=%d",
                result.title, result.goal, result.audience, len(result.key_topics),
            )
            return result
        except Exception as e:
            logger.error("IntentAgent: analysis failed: %s", e)
            # Fallback: возвращаем базовый результат
            return IntentResult(
                title=query[:100],
                goal="inform",
                audience="general",
                tone="neutral",
                key_topics=[query[:200]],
                suggested_slide_count=8,
            )