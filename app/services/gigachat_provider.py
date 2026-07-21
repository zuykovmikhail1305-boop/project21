"""GigaChat provider: реализация LLMProvider для GigaChat API.

Использует OAuth 2.0 (client credentials) для аутентификации
и OpenAI-совместимый API для генерации текста.
"""

import asyncio
import json
import time
from typing import AsyncIterator, Optional

import httpx

from app.services.llm_provider import LLMProvider
from app.core import config


class GigaChatClient(LLMProvider):
    """GigaChat клиент с OAuth 2.0 аутентификацией.

    Особенности:
    - Client Credentials flow для получения токена
    - Автоматическое обновление токена по истечении срока
    - OpenAI-совместимый API (/chat/completions)
    - Поддержка стриминга
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        auth_url: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        self.client_id = client_id or config.GIGACHAT_CLIENT_ID
        self.client_secret = client_secret or config.GIGACHAT_CLIENT_SECRET
        self.scope = scope or config.GIGACHAT_SCOPE
        self.auth_url = (auth_url or config.GIGACHAT_AUTH_URL).rstrip("/")
        self.api_url = (api_url or config.GIGACHAT_API_URL).rstrip("/")

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        # Request new token
        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            response = await client.post(
                f"{self.auth_url}",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": self._generate_rquid(),
                },
                data={
                    "scope": self.scope,
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            # GigaChat tokens typically expire in 30 minutes (1800 seconds)
            expires_in = data.get("expires_in", 1800)
            self._token_expires_at = time.time() + expires_in

            return self._access_token

    def _generate_rquid(self) -> str:
        """Generate a unique RqUID header value (UUID4)."""
        import uuid
        return str(uuid.uuid4())

    async def _generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        parts = []
        async for chunk in self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            parts.append(chunk)
        return "".join(parts)

    def generate_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """Синхронная обёртка для генерации текста."""
        try:
            return asyncio.run(
                self._generate_text(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    stream=stream,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._generate_text(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        stream=stream,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                )
            finally:
                loop.close()

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Generate text using GigaChat API.

        Args:
            prompt: User prompt.
            system_prompt: Optional system message.
            stream: Whether to stream the response.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in response.

        Yields:
            Text chunks as they arrive (streaming) or full response.
        """
        token = await self._get_access_token()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            async with client.stream(
                "POST",
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": "GigaChat",
                    "messages": messages,
                    "stream": stream,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=120.0,
            ) as response:
                if stream:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                else:
                    result = await response.aread()
                    data = json.loads(result)
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    yield content

    def generate_embeddings_sync(self, text: str) -> list[float]:
        """Синхронная обёртка для эмбеддингов."""
        try:
            return asyncio.run(self.generate_embeddings(text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.generate_embeddings(text))
            finally:
                loop.close()

    async def generate_embeddings(self, text: str) -> list[float]:
        """Generate embeddings using GigaChat API.

        Note: GigaChat may not support embeddings directly.
        Falls back to a simple approach using the model itself,
        or raises NotImplementedError if not available.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        token = await self._get_access_token()

        async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
            response = await client.post(
                f"{self.api_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": "GigaChat",
                    "input": text,
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            elif response.status_code == 404:
                # GigaChat may not support embeddings endpoint
                raise NotImplementedError(
                    "GigaChat does not support embeddings. "
                    "Use sentence-transformers for embeddings instead."
                )
            else:
                response.raise_for_status()
                return []  # unreachable
