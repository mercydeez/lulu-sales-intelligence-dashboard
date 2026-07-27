"""OpenAI provider — optional paid backend."""
import json
from typing import AsyncGenerator, Dict, List

import httpx

from .base import LLMError, LLMProvider

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 1500,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", OPENAI_API_URL, headers=self._headers(), json=payload
                ) as response:
                    if response.status_code != 200:
                        raise LLMError(f"OpenAI returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if choices:
                            content = choices[0].get("delta", {}).get("content", "")
                            if content:
                                yield content
        except (httpx.HTTPError, OSError) as e:
            raise LLMError(f"OpenAI unreachable: {e}") from e

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1500,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    OPENAI_API_URL, headers=self._headers(), json=payload
                )
                if response.status_code != 200:
                    raise LLMError(f"OpenAI returned HTTP {response.status_code}")
                return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, OSError, KeyError, IndexError) as e:
            raise LLMError(f"OpenAI request failed: {e}") from e
