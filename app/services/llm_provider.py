"""Абстрактный LLM провайдер и OpenAI-совместимый клиент для разработки."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

import httpx


class LLMProvider(ABC):
    """Абстрактный провайдер языковой модели."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Генерация текста. Поддерживает стриминг."""
        ...

    @abstractmethod
    async def generate_embeddings(self, text: str) -> list[float]:
        """Генерация эмбеддинга для текста."""
        ...


class OpenAIClient(LLMProvider):
    """OpenAI-совместимый клиент (для разработки с мок-сервером)."""

    def __init__(
        self,
        api_key: str = "sk-mock-key",
        api_base: str = "http://localhost:8000/v1",
        model: str = "gpt-4o-mini",
    ):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Генерация через OpenAI-совместимый API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60.0,
            ) as response:
                if stream:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            yield data
                else:
                    result = await response.aread()
                    yield result.decode()

    async def generate_embeddings(self, text: str) -> list[float]:
        """Генерация эмбеддинга через OpenAI-совместимый API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "text-embedding-ada-002",
                    "input": text,
                },
                timeout=30.0,
            )
            result = response.json()
            return result["data"][0]["embedding"]