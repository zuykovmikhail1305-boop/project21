"""ThemeManager: управление темами оформления артефактов.

Темы определяют корпоративный стиль: шрифты, цвета, отступы, логотип,
колонтитулы, палитру графиков и кастомные layout'ы слайдов.

Системные темы загружаются из seed SQL.
Пользовательские темы можно создавать через API.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.artifact_v2 import Theme as ThemeDB
from app.services.artifact.models import Theme, ThemeColors, ThemeFonts

logger = logging.getLogger(__name__)


# Системные темы (дубликат seed SQL для использования без БД)
SYSTEM_THEMES: dict[str, dict[str, Any]] = {
    "corporate": {
        "name": "corporate",
        "display_name": "Corporate",
        "config": {
            "fonts": {"heading": "Arial", "body": "Arial", "size_heading": 28, "size_body": 14},
            "colors": {
                "primary": "#0052CC",
                "secondary": "#7A869A",
                "background": "#FFFFFF",
                "text": "#172B4D",
                "accent": "#00B8D9",
                "success": "#36B37E",
                "warning": "#FFAB00",
                "error": "#FF5630",
            },
            "margins": {"top": 20, "bottom": 20, "left": 30, "right": 30},
            "chart_palette": [
                "#0052CC", "#00B8D9", "#36B37E",
                "#FFAB00", "#FF5630", "#6554C0", "#7A869A",
            ],
        },
    },
    "dark": {
        "name": "dark",
        "display_name": "Dark",
        "config": {
            "fonts": {"heading": "Arial", "body": "Arial", "size_heading": 28, "size_body": 14},
            "colors": {
                "primary": "#4C9AFF",
                "secondary": "#A5ADBA",
                "background": "#1A1A2E",
                "text": "#FFFFFF",
                "accent": "#00B8D9",
                "success": "#36B37E",
                "warning": "#FFAB00",
                "error": "#FF5630",
            },
            "margins": {"top": 20, "bottom": 20, "left": 30, "right": 30},
            "chart_palette": [
                "#4C9AFF", "#00B8D9", "#36B37E",
                "#FFAB00", "#FF5630", "#6554C0", "#A5ADBA",
            ],
        },
    },
    "minimal": {
        "name": "minimal",
        "display_name": "Minimal",
        "config": {
            "fonts": {"heading": "Helvetica", "body": "Helvetica", "size_heading": 24, "size_body": 12},
            "colors": {
                "primary": "#333333",
                "secondary": "#666666",
                "background": "#FFFFFF",
                "text": "#000000",
                "accent": "#555555",
                "success": "#2E7D32",
                "warning": "#F57F17",
                "error": "#C62828",
            },
            "margins": {"top": 15, "bottom": 15, "left": 25, "right": 25},
            "chart_palette": [
                "#333333", "#555555", "#777777",
                "#999999", "#BBBBBB", "#DDDDDD", "#EEEEEE",
            ],
        },
    },
}


def _config_to_theme(config: dict[str, Any]) -> Theme:
    """Преобразовать словарь конфигурации в Pydantic Theme.

    Args:
        config: Словарь с полями fonts, colors, margins, chart_palette, logo, header, footer.

    Returns:
        Theme Pydantic модель.
    """
    fonts_data = config.get("fonts", {})
    colors_data = config.get("colors", {})

    return Theme(
        name=config.get("name", "custom"),
        display_name=config.get("display_name", "Custom"),
        fonts=ThemeFonts(
            heading=fonts_data.get("heading", "Arial"),
            body=fonts_data.get("body", "Arial"),
            size_heading=fonts_data.get("size_heading", 28),
            size_body=fonts_data.get("size_body", 14),
        ),
        colors=ThemeColors(
            primary=colors_data.get("primary", "#0052CC"),
            secondary=colors_data.get("secondary", "#7A869A"),
            background=colors_data.get("background", "#FFFFFF"),
            text=colors_data.get("text", "#172B4D"),
            accent=colors_data.get("accent", "#00B8D9"),
            success=colors_data.get("success", "#36B37E"),
            warning=colors_data.get("warning", "#FFAB00"),
            error=colors_data.get("error", "#FF5630"),
        ),
        margins=config.get("margins", {"top": 20, "bottom": 20, "left": 30, "right": 30}),
        logo=config.get("logo"),
        header=config.get("header"),
        footer=config.get("footer"),
        chart_palette=config.get("chart_palette", [
            "#0052CC", "#00B8D9", "#36B37E",
            "#FFAB00", "#FF5630", "#6554C0", "#7A869A",
        ]),
        slide_layouts=config.get("slide_layouts", {}),
    )


class ThemeManager:
    """Управление темами оформления артефактов."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def get_theme(self, name: str) -> Optional[Theme]:
        """Получить тему по имени.

        Сначала ищет в БД, потом в системных темах.
        Возвращает Pydantic Theme модель.

        Args:
            name: Имя темы (например, "corporate", "dark", "minimal").

        Returns:
            Theme Pydantic модель или None, если тема не найдена.
        """
        # Из БД
        if self.db:
            theme_db = (
                self.db.query(ThemeDB)
                .filter(ThemeDB.name == name)
                .first()
            )
            if theme_db:
                # theme_db.config — dict[str, Any] в runtime (Pylance false positive)
                config: dict[str, Any] = theme_db.config  # type: ignore[assignment]
                config["name"] = theme_db.name  # type: ignore[index]
                config["display_name"] = theme_db.display_name  # type: ignore[index]
                return _config_to_theme(config)

        # Из системных тем
        if name in SYSTEM_THEMES:
            data = SYSTEM_THEMES[name]
            config = dict(data["config"])
            config["name"] = data["name"]
            config["display_name"] = data["display_name"]
            return _config_to_theme(config)

        return None

    def list_themes(self) -> list[dict[str, Any]]:
        """Список всех тем (системные + пользовательские).

        Returns:
            Список словарей с полями: id, name, display_name, is_system.
        """
        themes: list[dict[str, Any]] = []

        # Из БД
        if self.db:
            db_themes = (
                self.db.query(ThemeDB)
                .order_by(ThemeDB.is_system.desc(), ThemeDB.name)
                .all()
            )
            for t in db_themes:
                themes.append({
                    "id": t.id,
                    "name": t.name,
                    "display_name": t.display_name,
                    "is_system": t.is_system,
                })

        # Системные (если не в БД)
        existing_names = {t["name"] for t in themes}
        for name, data in SYSTEM_THEMES.items():
            if name not in existing_names:
                themes.append({
                    "name": data["name"],
                    "display_name": data["display_name"],
                    "is_system": True,
                })

        return themes

    def get_default_theme(self) -> Theme:
        """Получить тему по умолчанию (corporate).

        Returns:
            Theme Pydantic модель с корпоративной темой.
        """
        return _config_to_theme(SYSTEM_THEMES["corporate"]["config"])

    def create_theme(
        self,
        name: str,
        display_name: str,
        config: dict[str, Any],
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Создать пользовательскую тему.

        Args:
            name: Уникальное имя темы.
            display_name: Отображаемое название.
            config: Полная конфигурация темы (поля Theme Pydantic модели).
            user_id: ID пользователя-владельца (опционально).

        Returns:
            Словарь с id, name, display_name, is_system.

        Raises:
            RuntimeError: Если нет подключения к БД.
            ValueError: Если тема с таким именем уже существует.
        """
        if not self.db:
            raise RuntimeError("Database required for creating themes")

        existing = (
            self.db.query(ThemeDB)
            .filter(ThemeDB.name == name)
            .first()
        )
        if existing:
            raise ValueError(f"Theme already exists: {name}")

        theme = ThemeDB(
            name=name,
            display_name=display_name,
            config=config,
            is_system=False,
            user_id=user_id,
        )
        self.db.add(theme)
        self.db.commit()
        self.db.refresh(theme)

        logger.info("Theme created: %s (id=%d)", name, theme.id)
        return {
            "id": theme.id,
            "name": theme.name,
            "display_name": theme.display_name,
            "is_system": False,
        }

    def delete_theme(self, theme_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить тему.

        Args:
            theme_id: ID темы в БД.
            user_id: ID пользователя для проверки владельца (опционально).

        Returns:
            True если удалена, False если не найдена.

        Raises:
            ValueError: Если попытка удалить системную тему.
            PermissionError: Если пользователь не владелец темы.
        """
        if not self.db:
            return False

        theme = (
            self.db.query(ThemeDB)
            .filter(ThemeDB.id == theme_id)
            .first()
        )
        if not theme:
            return False
        if theme.is_system:
            raise ValueError("Cannot delete system theme")
        if user_id and theme.user_id != user_id:
            raise PermissionError("Not your theme")

        self.db.delete(theme)
        self.db.commit()
        logger.info("Theme deleted: id=%d", theme_id)
        return True

    def update_theme(
        self,
        theme_id: int,
        display_name: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Обновить пользовательскую тему.

        Args:
            theme_id: ID темы в БД.
            display_name: Новое отображаемое название (опционально).
            config: Новая конфигурация темы (опционально).
            user_id: ID пользователя для проверки владельца (опционально).

        Returns:
            Словарь с id, name, display_name, is_system или None если не найдена.

        Raises:
            ValueError: Если попытка изменить системную тему.
            PermissionError: Если пользователь не владелец темы.
        """
        if not self.db:
            return None

        theme = (
            self.db.query(ThemeDB)
            .filter(ThemeDB.id == theme_id)
            .first()
        )
        if not theme:
            return None
        if theme.is_system:
            raise ValueError("Cannot modify system theme")
        if user_id and theme.user_id != user_id:
            raise PermissionError("Not your theme")

        if display_name is not None:
            theme.display_name = display_name
        if config is not None:
            theme.config = config

        self.db.commit()
        self.db.refresh(theme)

        logger.info("Theme updated: id=%d", theme_id)
        return {
            "id": theme.id,
            "name": theme.name,
            "display_name": theme.display_name,
            "is_system": False,
        }