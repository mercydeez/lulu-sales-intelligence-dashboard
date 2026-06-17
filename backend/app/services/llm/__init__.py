"""
LLM provider abstraction (Phase 2.5).

Providers are tried in priority order — Ollama (local, free) first when
configured, then OpenAI when a key is present. When neither is available or
a call fails, the caller falls back to the rule-based responder, so the AI
assistant always answers with real data and zero paid keys.
"""
from typing import List

from app.config import get_settings

from .base import LLMError, LLMProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider


def get_provider_chain() -> List[LLMProvider]:
    """Configured providers in the order they should be attempted."""
    settings = get_settings()
    chain: List[LLMProvider] = []
    if settings.ollama_url:
        chain.append(OllamaProvider(settings.ollama_url, settings.ollama_model))
    if settings.openai_api_key:
        chain.append(OpenAIProvider(settings.openai_api_key))
    return chain


__all__ = ["LLMError", "LLMProvider", "OllamaProvider", "OpenAIProvider", "get_provider_chain"]
