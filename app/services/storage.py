"""Абстракция хранилища файлов и Mock-реализация для MVP."""

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO


class StorageProvider(ABC):
    """Абстрактный провайдер хранилища файлов."""

    @abstractmethod
    async def upload(self, file_path: str, content: BinaryIO) -> str:
        """Загрузить файл в хранилище. Возвращает путь в хранилище."""
        ...

    @abstractmethod
    async def download(self, storage_path: str, local_path: str) -> str:
        """Скачать файл из хранилища в локальную файловую систему."""
        ...

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Удалить файл из хранилища."""
        ...

    @abstractmethod
    async def list_files(self, prefix: str = "") -> list[dict]:
        """Список файлов в хранилище."""
        ...

    @abstractmethod
    async def get_file_info(self, storage_path: str) -> dict:
        """Получить информацию о файле."""
        ...


class MockStorageProvider(StorageProvider):
    """Mock-реализация хранилища на локальной файловой системе."""

    def __init__(self, storage_path: str = "./storage"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def upload(self, file_path: str, content: BinaryIO) -> str:
        """Сохранить файл локально."""
        dest = self.storage_path / file_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        with open(dest, "wb") as f:
            shutil.copyfileobj(content, f)

        return str(dest)

    async def download(self, storage_path: str, local_path: str) -> str:
        """Скопировать файл из хранилища в локальную папку."""
        src = self.storage_path / storage_path
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src, dest)
        return str(dest)

    async def delete(self, storage_path: str) -> None:
        """Удалить файл."""
        path = self.storage_path / storage_path
        if path.exists():
            path.unlink()

    async def list_files(self, prefix: str = "") -> list[dict]:
        """Список файлов в хранилище."""
        search_path = self.storage_path / prefix
        if not search_path.exists():
            return []

        files = []
        for f in search_path.rglob("*"):
            if f.is_file():
                files.append({
                    "path": str(f.relative_to(self.storage_path)),
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        return files

    async def get_file_info(self, storage_path: str) -> dict:
        """Информация о файле."""
        path = self.storage_path / storage_path
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")

        return {
            "path": str(path.relative_to(self.storage_path)),
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
            "exists": True,
        }