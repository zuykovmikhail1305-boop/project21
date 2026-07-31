"""AssetResolver: Lazy resolution AssetReference → Asset.

Генерирует ассет ТОЛЬКО когда он реально нужен (lazy).
Вызывает нужный Builder по типу ассета.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from app.services.artifact.asset_manager import AssetManager
from app.services.artifact.chart_builder import ChartBuilder
from app.services.artifact.diagram_builder import DiagramBuilder
from app.services.artifact.formula_builder import FormulaBuilder
from app.services.artifact.models import (
    ArtifactAsset,
    AssetReference,
    AssetType,
    Theme,
)

logger = logging.getLogger(__name__)


class AssetResolver:
    """Lazy resolution: AssetReference → Asset.

    Генерирует ассет только когда renderer действительно до него дошёл.
    """

    def __init__(
        self,
        asset_manager: Optional[AssetManager] = None,
        chart_builder: Optional[ChartBuilder] = None,
        diagram_builder: Optional[DiagramBuilder] = None,
        formula_builder: Optional[FormulaBuilder] = None,
    ):
        self.asset_manager = asset_manager or AssetManager()
        self.chart_builder = chart_builder or ChartBuilder()
        self.diagram_builder = diagram_builder or DiagramBuilder()
        self.formula_builder = formula_builder or FormulaBuilder()

    async def resolve(
        self,
        ref: AssetReference,
        data: dict[str, pd.DataFrame],
        theme: Theme,
    ) -> ArtifactAsset:
        """Разрешить ассет. Генерирует только если status=pending.

        Args:
            ref: Ссылка на ассет (может быть pending или уже resolved).
            data: Словарь с DataFrame'ами по источникам данных.
            theme: Тема оформления.

        Returns:
            ArtifactAsset — resolved ассет.
        """
        # Уже разрешён — возвращаем
        if ref.status == "resolved" and ref.resolved_asset:
            return ref.resolved_asset

        # Проверяем в AssetManager (уже сгенерирован ранее)
        existing = self.asset_manager.get(ref.asset_id)
        if existing:
            ref.status = "resolved"
            ref.resolved_asset = existing
            return existing

        # Генерируем в зависимости от типа
        logger.info(
            "Resolving asset: id=%s type=%s source=%s",
            ref.asset_id, ref.asset_type.value, ref.source,
        )

        if ref.asset_type == AssetType.CHART:
            asset = await self.chart_builder.build(ref, data, theme)

        elif ref.asset_type == AssetType.DIAGRAM:
            asset = await self.diagram_builder.build(ref, theme)

        elif ref.asset_type == AssetType.FORMULA:
            asset = await self.formula_builder.build(ref, theme)

        elif ref.asset_type == AssetType.TABLE:
            asset = await self._build_table(ref, theme)

        else:
            logger.warning("Unsupported asset type: %s", ref.asset_type)
            raise ValueError(f"Unsupported asset type: {ref.asset_type}")

        # Сохраняем через AssetManager
        saved = self.asset_manager.save(
            asset_id=asset.asset_id,
            asset_type=asset.asset_type,
            name=asset.name,
            content=open(asset.file_path, "rb").read(),
            mime_type=asset.mime_type,
            metadata=asset.metadata,
        )

        ref.status = "resolved"
        ref.resolved_asset = saved
        return saved

    async def resolve_all(
        self,
        refs: list[AssetReference],
        data: dict[str, pd.DataFrame],
        theme: Theme,
    ) -> dict[str, ArtifactAsset]:
        """Разрешить все ассеты из списка.

        Returns:
            dict[asset_id, ArtifactAsset].
        """
        result: dict[str, ArtifactAsset] = {}
        for ref in refs:
            if ref.status != "resolved":
                asset = await self.resolve(ref, data, theme)
                result[ref.asset_id] = asset
            elif ref.resolved_asset:
                result[ref.asset_id] = ref.resolved_asset
        return result

    async def _build_table(
        self,
        ref: AssetReference,
        theme: Theme,
    ) -> ArtifactAsset:
        """Построить таблицу как изображение (через matplotlib)."""
        import matplotlib.pyplot as plt
        import numpy as np

        headers = ref.spec.get("headers", [])
        rows = ref.spec.get("rows", [])

        if not headers or not rows:
            raise ValueError("Table has no data")

        fig, ax = plt.subplots(figsize=(len(headers) * 1.5, len(rows) * 0.5 + 0.5))
        ax.axis("off")

        table_data = [[str(cell) for cell in row] for row in rows]
        table = ax.table(
            cellText=table_data,
            colLabels=headers,
            loc="center",
            cellLoc="left",
        )

        # Стиль
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.5)

        for key, cell in table.get_celld().items():
            if key[0] == 0:  # header
                cell.set_facecolor(theme.colors.primary)
                cell.set_text_props(color="white", weight="bold")
            elif key[0] % 2 == 0:
                cell.set_facecolor("#F5F5F5")
            else:
                cell.set_facecolor("white")

        file_path = f"/tmp/artifacts/assets/table/{ref.asset_id}_table.png"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        plt.savefig(file_path, dpi=200, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)

        return ArtifactAsset(
            asset_id=ref.asset_id,
            asset_type=AssetType.TABLE,
            name=f"{ref.asset_id}_table.png",
            mime_type="image/png",
            file_path=file_path,
            metadata={"headers": headers, "rows": len(rows)},
            size_bytes=os.path.getsize(file_path),
        )


import os  # noqa: E402 (needed for _build_table)