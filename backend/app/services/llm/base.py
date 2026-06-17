"""Common interface every LLM provider implements."""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List


class LLMError(Exception):
    """Raised by providers on any upstream failure so callers can fall through
    to the next provider in the chain."""


class LLMProvider(ABC):
    """A chat-completion backend. Implementations must raise LLMError on
    upstream failure (timeouts, 4xx/5xx, connection refused) rather than
    returning partial output."""

    name: str = "base"

    @abstractmethod
    def stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Yield response text chunks for the conversation."""

    @abstractmethod
    async def complete(self, messages: List[Dict[str, str]]) -> str:
        """Return the full response text for the conversation."""
