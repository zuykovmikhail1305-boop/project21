"""ChartBuilder: ChartBlock description → chart.png.

Без LLM. Сам выбирает тип графика по характеру данных.
Получает Theme.chart_palette — не знает о цветах.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.services.artifact.models import (
    ArtifactAsset,
    AssetReference,
    AssetType,
    Theme,
)

logger = logging.getLogger(__name__)


class ChartBuilder:
    """Построение графиков по смысловому описанию.

    ChartBuilder сам выбирает тип графика (bar/line/pie/etc.)
    на основе характера данных, а не получает его от LLM.
    """

    def __init__(self, output_dir: str = "/tmp/artifacts/assets/chart"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    async def build(
        self,
        ref: AssetReference,
        data: dict[str, pd.DataFrame],
        theme: Theme,
    ) -> ArtifactAsset:
        """Построить график по AssetReference.

        Args:
            ref: Ссылка на ассет с spec: {description, columns}.
            data: Словарь с DataFrame'ами по источникам данных.
            theme: Тема оформления (цвета, шрифты).

        Returns:
            ArtifactAsset с путём к PNG.
        """
        description = ref.spec.get("description", "")
        columns = ref.spec.get("columns", [])
        data_source = ref.source

        # Получаем данные
        df = data.get(data_source)
        if df is None and data:
            # Берём первый доступный DataFrame
            df = next(iter(data.values()))
        if df is None:
            df = self._generate_sample_data(columns)

        # Выбираем тип графика
        chart_type = self._choose_chart_type(df, columns, description)

        # Строим
        fig = self._render(chart_type, df, columns, description, theme)

        # Сохраняем
        file_path = os.path.join(self.output_dir, f"{ref.asset_id}_{chart_type}.png")
        fig.savefig(file_path, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        file_size = os.path.getsize(file_path)
        logger.info(
            "Chart built: id=%s type=%s desc=%s path=%s",
            ref.asset_id, chart_type, description[:50], file_path,
        )

        return ArtifactAsset(
            asset_id=ref.asset_id,
            asset_type=AssetType.CHART,
            name=f"{ref.asset_id}_{chart_type}.png",
            mime_type="image/png",
            file_path=file_path,
            metadata={
                "chart_type": chart_type,
                "description": description,
                "columns": columns,
            },
            size_bytes=file_size,
        )

    def _choose_chart_type(
        self,
        df: pd.DataFrame,
        columns: list[str],
        description: str,
    ) -> str:
        """Выбрать тип графика на основе данных.

        Правила выбора:
        - 1 категориальная + 1 числовая → bar
        - Временной ряд + число → line
        - 2+ числовых → scatter
        - Только категории → pie (если <= 7) / bar
        - description содержит "trend", "growth", "dynamics" → line
        - description содержит "compare", "comparison", "vs" → bar
        - description содержит "distribution", "spread" → scatter
        - description содержит "share", "percentage", "%" → pie
        """
        desc_lower = description.lower()

        # По описанию
        # Сначала более специфичные/конкретные ключевые слова
        if any(w in desc_lower for w in ["trend", "growth", "dynamics", "change over"]):
            return "line"
        if any(w in desc_lower for w in ["compare", "comparison", "vs", "versus"]):
            return "bar"
        # Доли/проценты — проверяем ДО distribution/scatter,
        # т.к. "percentage distribution" должно быть pie, а не scatter
        if any(w in desc_lower for w in ["share", "percentage", "%", "proportion"]):
            return "pie"
        if any(w in desc_lower for w in ["distribution", "spread", "correlation"]):
            return "scatter"

        # По данным
        if df.empty or len(columns) < 2:
            return "bar"

        x_col = columns[0]
        y_col = columns[1] if len(columns) > 1 else columns[0]

        # Проверяем, является ли x_col временным рядом
        if self._is_datetime(df, x_col):
            return "line"

        # Проверяем количество уникальных значений
        if df[x_col].nunique() <= 7 and df[y_col].dtype in (int, float):
            return "pie"

        # По умолчанию
        return "bar"

    def _render(
        self,
        chart_type: str,
        df: pd.DataFrame,
        columns: list[str],
        title: str,
        theme: Theme,
    ) -> Any:
        """Рендерит график указанного типа."""
        palette = theme.chart_palette

        if chart_type == "line":
            return self._render_line(df, columns, title, palette, theme)
        elif chart_type == "pie":
            return self._render_pie(df, columns, title, palette, theme)
        elif chart_type == "scatter":
            return self._render_scatter(df, columns, title, palette, theme)
        elif chart_type == "area":
            return self._render_area(df, columns, title, palette, theme)
        elif chart_type == "horizontal_bar":
            return self._render_horizontal_bar(df, columns, title, palette, theme)
        elif chart_type == "stacked_bar":
            return self._render_stacked_bar(df, columns, title, palette, theme)
        elif chart_type == "donut":
            return self._render_donut(df, columns, title, palette, theme)
        elif chart_type == "heatmap":
            return self._render_heatmap(df, columns, title, palette, theme)
        else:  # bar (default)
            return self._render_bar(df, columns, title, palette, theme)

    def _setup_figure(self, title: str, theme: Theme) -> tuple[Any, Any]:
        """Настроить общий стиль фигуры."""
        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor(theme.colors.background)
        ax.set_facecolor(theme.colors.background)
        ax.set_title(
            title,
            fontsize=theme.fonts.size_heading,
            fontfamily=theme.fonts.heading,
            color=theme.colors.text,
            pad=15,
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(theme.colors.secondary)
        ax.spines["bottom"].set_color(theme.colors.secondary)
        ax.tick_params(colors=theme.colors.text, labelsize=theme.fonts.size_body)
        return fig, ax

    def _render_bar(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> Any:
        fig, ax = self._setup_figure(title, theme)
        x_col = columns[0] if columns else df.columns[0]
        y_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else x_col
        bars = ax.bar(df[x_col].astype(str), df[y_col], color=palette[0], edgecolor="white", linewidth=0.5)
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height,
                    f"{height:.1f}", ha="center", va="bottom", fontsize=9, color=theme.colors.text)
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel(y_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.tight_layout()
        return fig

    def _render_line(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        x_col = columns[0] if columns else df.columns[0]
        y_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else x_col
        x_data = pd.to_datetime(df[x_col]) if self._is_datetime(df, x_col) else df[x_col].astype(str)
        ax.plot(x_data, df[y_col], color=palette[0], linewidth=2.5, marker="o", markersize=6)
        ax.fill_between(range(len(df)), df[y_col], alpha=0.1, color=palette[0])
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel(y_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        return fig

    def _render_pie(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(7, 7))
        fig.patch.set_facecolor(theme.colors.background)
        labels_col = columns[0] if columns else df.columns[0]
        values_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else labels_col
        colors = palette[:df[labels_col].nunique()]
        wedges, texts, autotexts = ax.pie(
            df[values_col], labels=df[labels_col].astype(str),
            colors=colors, autopct="%1.1f%%",
            startangle=90, pctdistance=0.85,
            textprops={"fontsize": theme.fonts.size_body, "color": theme.colors.text},
        )
        ax.set_title(title, fontsize=theme.fonts.size_heading, color=theme.colors.text, pad=15)
        plt.tight_layout()
        return fig

    def _render_scatter(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        x_col = columns[0] if columns else df.columns[0]
        y_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else x_col
        ax.scatter(df[x_col], df[y_col], c=palette[0], alpha=0.6, s=50, edgecolors="white", linewidth=0.5)
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel(y_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.tight_layout()
        return fig

    def _render_area(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        x_col = columns[0] if columns else df.columns[0]
        y_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else x_col
        x_data = pd.to_datetime(df[x_col]) if self._is_datetime(df, x_col) else range(len(df))
        ax.fill_between(range(len(df)), df[y_col], alpha=0.3, color=palette[0])
        ax.plot(range(len(df)), df[y_col], color=palette[0], linewidth=2)
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel(y_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.tight_layout()
        return fig

    def _render_horizontal_bar(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        y_col = columns[0] if columns else df.columns[0]
        x_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else y_col
        bars = ax.barh(df[y_col].astype(str), df[x_col], color=palette[0], edgecolor="white")
        for bar in bars:
            width = bar.get_width()
            ax.text(width + 0.1, bar.get_y() + bar.get_height() / 2.,
                    f"{width:.1f}", ha="left", va="center", fontsize=9, color=theme.colors.text)
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel(y_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.tight_layout()
        return fig

    def _render_stacked_bar(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        x_col = columns[0] if columns else df.columns[0]
        numeric_cols = [c for c in df.columns if df[c].dtype in (int, float) and c != x_col][:len(palette)]
        if not numeric_cols:
            numeric_cols = [columns[1]] if len(columns) > 1 else [df.columns[1]]
        x = np.arange(len(df))
        bottom = np.zeros(len(df))
        for i, col in enumerate(numeric_cols):
            bars = ax.bar(x, df[col], bottom=bottom, color=palette[i % len(palette)],
                          label=col, edgecolor="white", linewidth=0.3)
            bottom += df[col].values
        ax.set_xticks(x)
        ax.set_xticklabels(df[x_col].astype(str), rotation=45, ha="right")
        ax.legend(fontsize=9)
        ax.set_xlabel(x_col, fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        ax.set_ylabel("Value", fontsize=theme.fonts.size_body, color=theme.colors.secondary)
        plt.tight_layout()
        return fig

    def _render_donut(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(7, 7))
        fig.patch.set_facecolor(theme.colors.background)
        labels_col = columns[0] if columns else df.columns[0]
        values_col = columns[1] if len(columns) > 1 else df.columns[1] if len(df.columns) > 1 else labels_col
        colors = palette[:df[labels_col].nunique()]
        wedges, texts, autotexts = ax.pie(
            df[values_col], labels=df[labels_col].astype(str),
            colors=colors, autopct="%1.1f%%",
            startangle=90, pctdistance=0.78,
            wedgeprops={"width": 0.4, "edgecolor": "white"},
            textprops={"fontsize": theme.fonts.size_body, "color": theme.colors.text},
        )
        ax.set_title(title, fontsize=theme.fonts.size_heading, color=theme.colors.text, pad=15)
        plt.tight_layout()
        return fig

    def _render_heatmap(
        self, df: pd.DataFrame, columns: list[str],
        title: str, palette: list[str], theme: Theme,
    ) -> plt.Figure:
        fig, ax = self._setup_figure(title, theme)
        numeric_df = df.select_dtypes(include=[int, float])
        if numeric_df.empty:
            numeric_df = pd.DataFrame(np.random.rand(5, 5))
        im = ax.imshow(numeric_df.values, cmap="Blues", aspect="auto")
        plt.colorbar(im, ax=ax, shrink=0.8)
        ax.set_xticks(range(len(numeric_df.columns)))
        ax.set_xticklabels(numeric_df.columns, rotation=45, ha="right", fontsize=9)
        ax.set_yticks(range(len(numeric_df.index)))
        ax.set_yticklabels(numeric_df.index.astype(str), fontsize=9)
        plt.tight_layout()
        return fig

    def _is_datetime(self, df: pd.DataFrame, col: str) -> bool:
        """Проверить, является ли колонка datetime.

        Проверяет что:
        1. Колонка существует
        2. pd.to_datetime() не падает с ошибкой
        3. После парсинга нет NaT (невалидные даты)
        4. Год в разумном диапазоне (1900-2100) — чтобы отличить
           "Jan", "2024-Q1" от настоящих дат
        """
        if col not in df.columns:
            return False
        try:
            # Числовые колонки (int, float) не могут быть датами
            if df[col].dtype in (int, float, "int64", "float64"):
                return False
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.isna().any():
                return False
            # Проверяем что год в разумном диапазоне,
            # чтобы "Jan", "Feb" не считались датами
            first_val = parsed.iloc[0]
            if hasattr(first_val, "year"):
                year = first_val.year
                if year < 1900 or year > 2100:
                    return False
            return True
        except (ValueError, TypeError):
            return False

    def _generate_sample_data(self, columns: list[str]) -> pd.DataFrame:
        """Сгенерировать демо-данные, если реальных нет."""
        if not columns:
            columns = ["category", "value"]
        n = 6
        data: dict[str, Any] = {}
        for col in columns:
            if col in ("month", "months", "date", "year", "period"):
                data[col] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"][:n]
            elif col in ("category", "categories", "group", "segment", "region"):
                data[col] = [f"Cat {i}" for i in range(1, n + 1)]
            else:
                data[col] = np.random.randint(10, 100, n)
        return pd.DataFrame(data)