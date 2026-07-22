"""TemplateManager: управление шаблонами артефактов.

Шаблоны определяют предопределённую структуру документа.
Системные шаблоны загружаются из seed SQL.
Пользовательские шаблоны можно создавать через API.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.artifact_v2 import ArtifactTemplate
from app.services.artifact.models import ArtifactPlan

logger = logging.getLogger(__name__)


# Системные шаблоны (дубликат seed SQL для использования без БД)
SYSTEM_TEMPLATES: dict[str, dict[str, Any]] = {
    "corporate_report": {
        "name": "corporate_report",
        "display_name": "Corporate Report",
        "description": "Корпоративный отчёт: титул → оглавление → executive summary → секции → приложения",
        "schema": {
            "type": "object",
            "properties": {
                "sections": {"type": "array", "items": {"type": "object"}},
            },
        },
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "{{title}}"},
            {"type": "paragraph", "text": "{{date}}"},
        ],
    },
    "executive_summary": {
        "name": "executive_summary",
        "display_name": "Executive Summary",
        "description": "Executive Summary: ключевые метрики → выводы → рекомендации",
        "schema": {
            "type": "object",
            "properties": {
                "sections": {"type": "array"},
            },
        },
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "Executive Summary"},
        ],
    },
    "quarterly_report": {
        "name": "quarterly_report",
        "display_name": "Quarterly Report",
        "description": "Квартальный отчёт: обзор → финансы → операционные показатели → прогноз",
        "schema": {"type": "object", "properties": {"sections": {"type": "array"}}},
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "{{title}}"},
        ],
    },
    "investor_deck": {
        "name": "investor_deck",
        "display_name": "Investor Deck",
        "description": "Инвест-питч: проблема → решение → рынок → traction → команда → финансовые прогнозы",
        "schema": {"type": "object", "properties": {"sections": {"type": "array"}}},
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "{{title}}"},
        ],
    },
    "technical_proposal": {
        "name": "technical_proposal",
        "display_name": "Technical Proposal",
        "description": "Техническое предложение: контекст → архитектура → план → бюджет",
        "schema": {"type": "object", "properties": {"sections": {"type": "array"}}},
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "{{title}}"},
        ],
    },
    "architecture_review": {
        "name": "architecture_review",
        "display_name": "Architecture Review",
        "description": "Architecture Review: контекст → текущая архитектура → проблемы → рекомендации",
        "schema": {"type": "object", "properties": {"sections": {"type": "array"}}},
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "Architecture Review"},
        ],
    },
    "incident_report": {
        "name": "incident_report",
        "display_name": "Incident Report",
        "description": "Инцидент-репорт: хронология → root cause → impact → action items",
        "schema": {"type": "object", "properties": {"sections": {"type": "array"}}},
        "default_blocks": [
            {"type": "heading", "level": 1, "text": "Incident Report"},
        ],
    },
}


class TemplateManager:
    """Управление шаблонами артефактов."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def get_template(self, name: str) -> Optional[dict[str, Any]]:
        """Получить шаблон по имени.

        Сначала ищет в БД, потом в системных шаблонах.
        """
        # Из БД
        if self.db:
            template = (
                self.db.query(ArtifactTemplate)
                .filter(ArtifactTemplate.name == name)
                .first()
            )
            if template:
                return {
                    "id": template.id,
                    "name": template.name,
                    "display_name": template.display_name,
                    "description": template.description,
                    "schema": template.schema,
                    "default_blocks": template.default_blocks,
                    "is_system": template.is_system,
                }

        # Из системных шаблонов
        if name in SYSTEM_TEMPLATES:
            return SYSTEM_TEMPLATES[name]

        return None

    def list_templates(self) -> list[dict[str, Any]]:
        """Список всех шаблонов (системные + пользовательские)."""
        templates = []

        # Из БД
        if self.db:
            db_templates = (
                self.db.query(ArtifactTemplate)
                .order_by(ArtifactTemplate.is_system.desc(), ArtifactTemplate.name)
                .all()
            )
            for t in db_templates:
                templates.append({
                    "id": t.id,
                    "name": t.name,
                    "display_name": t.display_name,
                    "description": t.description,
                    "is_system": t.is_system,
                })

        # Системные (если не в БД)
        existing_names = {t["name"] for t in templates}
        for name, data in SYSTEM_TEMPLATES.items():
            if name not in existing_names:
                templates.append({
                    "name": data["name"],
                    "display_name": data["display_name"],
                    "description": data["description"],
                    "is_system": True,
                })

        return templates

    def apply_template(
        self,
        template_name: str,
        variables: Optional[dict[str, str]] = None,
    ) -> ArtifactPlan:
        """Применить шаблон и создать ArtifactPlan.

        Args:
            template_name: Имя шаблона.
            variables: Переменные для подстановки ({{title}}, {{date}}, ...).

        Returns:
            ArtifactPlan с структурой из шаблона.
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")

        variables = variables or {}
        default_blocks = template.get("default_blocks", [])

        # Подстановка переменных
        resolved_blocks = self._resolve_variables(default_blocks, variables)

        title = variables.get("title") or template["display_name"]
        return ArtifactPlan(
            title=title,
            sections=[{"title": template["display_name"], "blocks": resolved_blocks}],
        )

    def create_template(
        self,
        name: str,
        display_name: str,
        description: str,
        schema: dict,
        default_blocks: list[dict],
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Создать пользовательский шаблон."""
        if not self.db:
            raise RuntimeError("Database required for creating templates")

        existing = (
            self.db.query(ArtifactTemplate)
            .filter(ArtifactTemplate.name == name)
            .first()
        )
        if existing:
            raise ValueError(f"Template already exists: {name}")

        template = ArtifactTemplate(
            name=name,
            display_name=display_name,
            description=description,
            schema=schema,
            default_blocks=default_blocks,
            is_system=False,
            user_id=user_id,
        )
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)

        logger.info("Template created: %s (id=%d)", name, template.id)
        return {
            "id": template.id,
            "name": template.name,
            "display_name": template.display_name,
            "is_system": False,
        }

    def delete_template(self, template_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить шаблон."""
        if not self.db:
            return False

        template = (
            self.db.query(ArtifactTemplate)
            .filter(ArtifactTemplate.id == template_id)
            .first()
        )
        if not template:
            return False
        if template.is_system:
            raise ValueError("Cannot delete system template")
        if user_id and template.user_id != user_id:
            raise PermissionError("Not your template")

        self.db.delete(template)
        self.db.commit()
        logger.info("Template deleted: id=%d", template_id)
        return True

    def _resolve_variables(
        self,
        blocks: list[dict[str, Any]],
        variables: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Подставить переменные в блоки."""
        resolved = []
        for block in blocks:
            block_str = json.dumps(block)
            for key, value in variables.items():
                block_str = block_str.replace("{{" + key + "}}", value)
            resolved.append(json.loads(block_str))
        return resolved