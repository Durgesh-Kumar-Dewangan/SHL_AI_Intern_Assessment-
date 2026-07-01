"""Thin async LLM client supporting multiple free/paid providers.

We deliberately avoid a heavy framework (LangChain) here: the assignment
needs exactly one capability -- "send system+messages, get text back" -- and
a ~120-line adapter is easier to reason about, test, and debug than a
framework dependency chain. Retry/backoff and timeout are handled explicitly.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception

from app.config import Settings

logger = logging.getLogger("shl_recommender.llm")


class LLMError(Exception):
    """Raised when the LLM provider cannot be reached or returns an unusable response."""


class _RateLimitError(LLMError):
    """Transient 429 rate-limit — safe to retry after a pause."""


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException, _RateLimitError))


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception(_is_retryable),
    )
    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Calls the configured provider and parses a JSON object from the reply.

        Every provider is asked (via prompt instructions) to return *only* a
        JSON object. We still defensively extract the first {...} block in
        case the model wraps it in prose or markdown fences.
        """
        if not self.settings.llm_configured:
            raise LLMError(
                "No LLM API key configured. Set LLM_API_KEY (and LLM_PROVIDER) "
                "in your environment. See .env.example."
            )

        provider = self.settings.llm_provider
        try:
            if provider == "groq":
                raw_text = await self._call_openai_compatible(
                    base_url="https://api.groq.com/openai/v1/chat/completions",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            elif provider == "openrouter":
                raw_text = await self._call_openai_compatible(
                    base_url="https://openrouter.ai/api/v1/chat/completions",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            elif provider == "openai":
                raw_text = await self._call_openai_compatible(
                    base_url="https://api.openai.com/v1/chat/completions",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            elif provider == "gemini":
                raw_text = await self._call_gemini(system_prompt, user_prompt)
            elif provider == "anthropic":
                raw_text = await self._call_anthropic(system_prompt, user_prompt)
            else:
                raise LLMError(f"Unsupported LLM provider: {provider}")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.error("LLM HTTP error: %s - %s", status, exc.response.text[:500])
            if status == 429:
                raise _RateLimitError(f"LLM provider returned HTTP 429 (rate limited)") from exc
            raise LLMError(f"LLM provider returned HTTP {status}") from exc

        return self._extract_json(raw_text)

    async def _call_openai_compatible(self, base_url: str, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        resp = await self._client.post(base_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.llm_model}:generateContent?key={self.settings.llm_api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.settings.llm_temperature,
                "maxOutputTokens": self.settings.llm_max_tokens,
                "responseMimeType": "application/json",
            },
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "x-api-key": self.settings.llm_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.llm_model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": self.settings.llm_max_tokens,
            "temperature": self.settings.llm_temperature,
        }
        resp = await self._client.post(
            "https://api.anthropic.com/v1/messages", headers=headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))

    @staticmethod
    def _extract_json(raw_text: str) -> dict[str, Any]:
        raw_text = raw_text.strip()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw_text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise LLMError(f"Could not parse JSON from LLM response: {raw_text[:300]}") from exc
        raise LLMError(f"LLM response contained no JSON object: {raw_text[:300]}")
