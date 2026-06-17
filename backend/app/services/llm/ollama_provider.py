"""Ollama provider — local models over the Ollama HTTP API."""
import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str = "llama3.2", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/chat", json=payload
                ) as response:
                    if response.status_code != 200:
                        raise LLMError(f"Ollama returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("error"):
                            raise LLMError(f"Ollama error: {chunk['error']}")
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            return
        except (httpx.HTTPError, OSError) as e:
            raise LLMError(f"Ollama unreachable: {e}") from e

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                if response.status_code != 200:
                    raise LLMError(f"Ollama returned HTTP {response.status_code}")
                data = response.json()
                if data.get("error"):
                    raise LLMError(f"Ollama error: {data['error']}")
                return data.get("message", {}).get("content", "")
        except (httpx.HTTPError, OSError) as e:
            raise LLMError(f"Ollama unreachable: {e}") from e
