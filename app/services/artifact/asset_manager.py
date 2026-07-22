"""AssetManager: CRUD, хранение и кэширование ассетов.

Управляет жизненным циклом ассетов:
- Создание (save)
- Чтение (get, list)
- Удаление (delete)
- Кэширование в памяти
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.services.artifact.models import ArtifactAsset, AssetType

logger = logging.getLogger(__name__)


class AssetManager:
    """Управление ассетами: сохранение, загрузка, кэширование."""

    def __init__(self, storage_dir: str = "/tmp/artifacts/assets"):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        self._cache: dict[str, ArtifactAsset] = {}

    def save(
        self,
        asset_id: str,
        asset_type: AssetType,
        name: str,
        content: bytes,
        mime_type: str,
        metadata: Optional[dict] = None,
    ) -> ArtifactAsset:
        """Сохранить ассет на диск.

        Args:
            asset_id: UUID ассета.
            asset_type: Тип ассета.
            name: Имя файла.
            content: Бинарное содержимое.
            mime_type: MIME-тип.
            metadata: Дополнительные метаданные.

        Returns:
            ArtifactAsset с заполненным file_path.
        """
        # Создаём поддиректорию по типу
        type_dir = os.path.join(self.storage_dir, asset_type.value)
        os.makedirs(type_dir, exist_ok=True)

        # Уникальное имя файла
        safe_name = f"{asset_id}_{name}"
        file_path = os.path.join(type_dir, safe_name)

        # Сохраняем
        with open(file_path, "wb") as f:
            f.write(content)

        file_size = os.path.getsize(file_path)

        asset = ArtifactAsset(
            asset_id=asset_id,
            asset_type=asset_type,
            name=name,
            mime_type=mime_type,
            file_path=file_path,
            metadata=metadata or {},
            size_bytes=file_size,
            created_at=datetime.now(),
        )

        # Кэшируем
        self._cache[asset_id] = asset

        logger.info(
            "Asset saved: id=%s type=%s path=%s size=%d",
            asset_id, asset_type.value, file_path, file_size,
        )
        return asset

    def get(self, asset_id: str) -> Optional[ArtifactAsset]:
        """Получить ассет по ID (из кэша или с диска)."""
        # Из кэша
        if asset_id in self._cache:
            return self._cache[asset_id]

        # Поиск на диске
        for root, _dirs, files in os.walk(self.storage_dir):
            for fname in files:
                if fname.startswith(asset_id):
                    file_path = os.path.join(root, fname)
                    if os.path.exists(file_path):
                        # Восстанавливаем метаданные из имени
                        asset = ArtifactAsset(
                            asset_id=asset_id,
                            asset_type=self._infer_type(root),
                            name=fname[len(asset_id) + 1:],
                            mime_type=self._infer_mime(fname),
                            file_path=file_path,
                            size_bytes=os.path.getsize(file_path),
                        )
                        self._cache[asset_id] = asset
                        return asset
        return None

    def delete(self, asset_id: str) -> bool:
        """Удалить ассет."""
        asset = self.get(asset_id)
        if not asset:
            return False

        try:
            if os.path.exists(asset.file_path):
                os.unlink(asset.file_path)
            self._cache.pop(asset_id, None)
            logger.info("Asset deleted: id=%s", asset_id)
            return True
        except OSError as e:
            logger.error("Failed to delete asset %s: %s", asset_id, e)
            return False

    def list_by_type(self, asset_type: AssetType) -> list[ArtifactAsset]:
        """Список ассетов по типу."""
        assets = []
        type_dir = os.path.join(self.storage_dir, asset_type.value)
        if not os.path.exists(type_dir):
            return assets

        for fname in os.listdir(type_dir):
            file_path = os.path.join(type_dir, fname)
            if os.path.isfile(file_path):
                asset_id = fname.split("_")[0]
                asset = ArtifactAsset(
                    asset_id=asset_id,
                    asset_type=asset_type,
                    name=fname[len(asset_id) + 1:],
                    mime_type=self._infer_mime(fname),
                    file_path=file_path,
                    size_bytes=os.path.getsize(file_path),
                )
                assets.append(asset)
        return assets

    def clear_cache(self) -> None:
        """Очистить кэш."""
        self._cache.clear()

    def cleanup_old(self, max_age_hours: int = 24) -> int:
        """Удалить ассеты старше N часов."""
        now = datetime.now().timestamp()
        removed = 0
        for root, _dirs, files in os.walk(self.storage_dir):
            for fname in files:
                file_path = os.path.join(root, fname)
                age_hours = (now - os.path.getmtime(file_path)) / 3600
                if age_hours > max_age_hours:
                    os.unlink(file_path)
                    removed += 1
        logger.info("Cleaned up %d old assets (>%dh)", removed, max_age_hours)
        return removed

    def _infer_type(self, dir_path: str) -> AssetType:
        """Определить тип ассета по имени директории."""
        dir_name = os.path.basename(dir_path)
        try:
            return AssetType(dir_name)
        except ValueError:
            return AssetType.IMAGE

    def _infer_mime(self, filename: str) -> str:
        """Определить MIME-тип по расширению."""
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".html": "text/html",
            ".csv": "text/csv",
            ".json": "application/json",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
        }
        return mime_map.get(ext, "application/octet-stream")