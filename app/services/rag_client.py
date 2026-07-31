"""HTTP-клиент для вызова RAG API (self-вызов через внутреннюю сеть)."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core import config

logger = logging.getLogger(__name__)


class RAGClient:
    """HTTP-клиент для вызова RAG API эндпоинтов.

    Используется внутренними сервисами (SearchRAGAgent, ETL Pipeline)
    для вызова RAG-операций через HTTP вместо прямого хардкода.

    Все методы передают JWT-токен в Authorization header.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 500.0,
    ):
        self.base_url = (base_url or config.SELF_API_URL).rstrip("/")
        self.token = token or ""
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def search(
        self,
        query: str,
        user_groups: list[int] | None = None,
        top_k: int = 20,
        history: list[dict] | None = None,
    ) -> list[dict]:
        """Поиск релевантных чанков через RAG API.

        Args:
            query: Поисковый запрос.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество результатов.
            history: История диалога для HyDE.

        Returns:
            Список чанков с метаданными.
        """
        payload = {
            "query": query,
            "user_groups": user_groups or [],
            "top_k": top_k,
            "history": history,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/rag/search",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "RAGClient.search: found %d chunks for query=%s",
                len(data.get("chunks", [])), query[:100],
            )
            return data.get("chunks", [])
        except httpx.HTTPStatusError as e:
            logger.error("RAGClient.search HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise
        except httpx.RequestError as e:
            logger.error("RAGClient.search request failed: %s", e)
            raise

    async def answer(
        self,
        query: str,
        user_groups: list[int] | None = None,
        top_k: int = 5,
        history: list[dict] | None = None,
    ) -> dict:
        """Получить ответ на вопрос через RAG API.

        Args:
            query: Вопрос пользователя.
            user_groups: Список ID групп пользователя (для ACL).
            top_k: Количество чанков для поиска.
            history: История диалога для HyDE.

        Returns:
            Словарь с ключами: answer, confidence, citations, chunks.
        """
        payload = {
            "query": query,
            "user_groups": user_groups or [],
            "top_k": top_k,
            "history": history,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/rag/answer",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "RAGClient.answer: answer_len=%d, n_chunks=%d",
                len(data.get("answer", "")), len(data.get("chunks", [])),
            )
            return data
        except httpx.HTTPStatusError as e:
            logger.error("RAGClient.answer HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise
        except httpx.RequestError as e:
            logger.error("RAGClient.answer request failed: %s", e)
            raise

    async def generate_hyde(
        self,
        query: str,
        history: list[dict] | None = None,
        split_chunks: bool = True,
        max_chunks: int = 5,
    ) -> list[str]:
        """Сгенерировать HyDE-документ через RAG API.

        Args:
            query: Запрос пользователя.
            history: История диалога.
            split_chunks: Разбить на чанки.
            max_chunks: Максимальное количество чанков.

        Returns:
            Список текстовых чанков HyDE-документа.
        """
        payload = {
            "query": query,
            "history": history,
            "split_chunks": split_chunks,
            "max_chunks": max_chunks,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/rag/hyde",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "RAGClient.generate_hyde: %d chunks for query=%s",
                len(data.get("chunks", [])), query[:100],
            )
            return data.get("chunks", [])
        except httpx.HTTPStatusError as e:
            logger.error("RAGClient.generate_hyde HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise
        except httpx.RequestError as e:
            logger.error("RAGClient.generate_hyde request failed: %s", e)
            raise

    async def index_document(
        self,
        file_path: str,
        document_id: int | None = None,
    ) -> list[dict]:
        """Проиндексировать документ через RAG API.

        Args:
            file_path: Путь к файлу документа.
            document_id: ID документа в БД (для ACL).

        Returns:
            Список точек, сохранённых в Qdrant.
        """
        payload = {
            "file_path": file_path,
            "document_id": document_id,
        }
        try:
            response = await self._client.post(
                f"{self.base_url}/rag/index",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "RAGClient.index_document: status=%s, points=%d for file=%s",
                data.get("status"), data.get("points_count", 0), file_path,
            )
            # Возвращаем points_count как заглушку (API не возвращает полные точки)
            return []
        except httpx.HTTPStatusError as e:
            logger.error("RAGClient.index_document HTTP error: %s - %s", e.response.status_code, e.response.text)
            raise
        except httpx.RequestError as e:
            logger.error("RAGClient.index_document request failed: %s", e)
            raise

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""
        await self._client.aclose()