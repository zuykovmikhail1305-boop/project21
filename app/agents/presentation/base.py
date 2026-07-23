"""Base class for presentation agents with shared LLM initialization.

All presentation agents inherit from BasePresentationAgent to get
consistent GigaChat (or fallback) LLM access.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from app.core import config

logger = logging.getLogger(__name__)

try:
    from langchain_gigachat import GigaChat as GigaChatLangChain
except Exception:  # pragma: no cover
    GigaChatLangChain = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None


class BasePresentationAgent:
    """Base class for all presentation agents.

    Provides:
    - Shared LLM initialization (GigaChat priority, OpenAI fallback)
    - Helper methods for structured output and prompt chains
    """

    def __init__(self) -> None:
        self._gigachat_llm: Any = None
        self._openai_llm: Any = None
        self.llm: Any = None

        self._init_gigachat()
        self._init_openai()

        # Select best available LLM
        self.llm = self._gigachat_llm or self._openai_llm
        if self.llm is None:
            logger.warning("No LLM available for presentation agent")

    def _init_gigachat(self) -> None:
        """Initialize GigaChat via langchain-gigachat."""
        if GigaChatLangChain is None:
            return

        has_creds = bool(
            getattr(config, "GIGACHAT_CLIENT_ID", "")
            and getattr(config, "GIGACHAT_CLIENT_SECRET", "")
        )
        if not has_creds:
            return

        try:
            self._gigachat_llm = GigaChatLangChain(
                credentials=config.GIGACHAT_CREDENTIALS,
                scope=config.GIGACHAT_SCOPE,
                base_url=config.GIGACHAT_API_URL,
                auth_url=config.GIGACHAT_AUTH_URL,
                model=config.GIGACHAT_MODEL,
                temperature=0.1,
                verify_ssl_certs=False,
                timeout=30,
            )
        except Exception as e:
            logger.warning("Failed to init GigaChat: %s", e)
            self._gigachat_llm = None

    def _init_openai(self) -> None:
        """Initialize ChatOpenAI as fallback."""
        if ChatOpenAI is None:
            return

        try:
            self._openai_llm = ChatOpenAI(
                model=config.OPENAI_MODEL,
                temperature=0.1,
                api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_API_BASE,
            )
        except Exception as e:
            logger.warning("Failed to init OpenAI fallback: %s", e)
            self._openai_llm = None

    def _build_chain(self, prompt_template: str) -> ChatPromptTemplate:
        """Build a prompt chain from a template string.

        Creates a (system, human) message pair. GigaChat's new API
        (api.giga.chat/v1) requires function-calling metadata (explicit_call)
        to appear in a user or function role message, not system.
        Using only a system message causes HTTP 422 with:
        "explicit_call should only appeal in user, function messages or random role messages"

        Args:
            prompt_template: String with {placeholder} variables.

        Returns:
            ChatPromptTemplate ready for .invoke() or .ainvoke().
        """
        return ChatPromptTemplate.from_messages([
            ("system", prompt_template),
            ("human", "{input}"),
        ])

    def _build_structured_chain(
        self, prompt_template: str, output_model: type
    ) -> Optional[Runnable]:
        """Build a chain with structured output (with_structured_output).

        Args:
            prompt_template: String with {placeholder} variables.
            output_model: Pydantic model class for structured output.

        Returns:
            Chain that returns output_model instances, or None if LLM unavailable.
        """
        if self.llm is None:
            return None
        prompt = self._build_chain(prompt_template)
        return prompt | self.llm.with_structured_output(output_model)

    def _build_text_chain(self, prompt_template: str) -> Optional[Runnable]:
        """Build a chain that returns raw text (for JSON mode).

        Args:
            prompt_template: String with {placeholder} variables.

        Returns:
            Chain that returns raw text, or None if LLM unavailable.
        """
        if self.llm is None:
            return None
        prompt = self._build_chain(prompt_template)
        return prompt | self.llm | StrOutputParser()