"""OpenAI-compatible chat completions client.

Works against llama.cpp's server, Ollama, LM Studio, vLLM, OpenRouter, OpenAI
and anything else that speaks ``POST /chat/completions``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from ..errors import LLMError
from .base import ChatMessage, LLMResponse, ToolCall, ToolSpec

log = logging.getLogger(__name__)


class OpenAICompatLLM:
    """Thin, dependency-light client for the OpenAI wire format."""

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        model: str = "local",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: float = 180.0,
        max_retries: int = 3,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not base_url:
            raise LLMError("base_url is required for the OpenAI-compatible client")
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1") and "/chat/completions" not in self.base_url:
            self.base_url = f"{self.base_url}/v1"
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_headers = extra_headers or {}

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stage: str = "",
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if tools:
            body["tools"] = [t.to_openai() for t in tools]
            body["tool_choice"] = "auto"

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self._endpoint(), json=body, headers=self._headers())
                if response.status_code >= 500:
                    raise LLMError(f"upstream {response.status_code}: {response.text[:300]}")
                if response.status_code == 400 and json_mode:
                    # Some servers reject response_format; retry without it.
                    body.pop("response_format", None)
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"upstream {response.status_code}: {response.text[:400]}")
                return self._parse(response.json())
            except (httpx.HTTPError, LLMError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = min(2 ** (attempt - 1), 8)
                log.warning("LLM call failed (attempt %d/%d): %s", attempt, self.max_retries, exc)
                await asyncio.sleep(delay)
        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def _parse(payload: dict[str, Any]) -> LLMResponse:
        try:
            choice = payload["choices"][0]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"malformed completion response: {payload}") from exc
        message = choice.get("message") or {}
        raw_calls = message.get("tool_calls") or []
        calls: list[ToolCall] = []
        for call in raw_calls:
            fn = call.get("function") or {}
            arguments = fn.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments) if arguments.strip() else {}
                except json.JSONDecodeError:
                    parsed = {"_raw": arguments}
            else:
                parsed = arguments
            calls.append(ToolCall(id=call.get("id", ""), name=fn.get("name", ""), arguments=parsed))
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            model=payload.get("model", ""),
            finish_reason=choice.get("finish_reason", ""),
            usage=payload.get("usage") or {},
        )

    async def health(self) -> dict[str, Any]:
        """Best-effort probe used by ``agentic doctor``."""
        url = self.base_url.replace("/chat/completions", "")
        if url.endswith("/v1"):
            url = url[:-3]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for candidate in (f"{url}/models", f"{self.base_url}/models"):
                    try:
                        resp = await client.get(candidate, headers=self._headers())
                    except httpx.HTTPError:
                        continue
                    if resp.status_code < 400:
                        data = resp.json()
                        items = data.get("data", data) if isinstance(data, dict) else data
                        ids = [i.get("id") for i in items if isinstance(i, dict)] if isinstance(items, list) else []
                        return {"ok": True, "endpoint": candidate, "models": ids[:20]}
                return {"ok": False, "endpoint": url, "error": "no /models endpoint responded"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "endpoint": url, "error": str(exc)}
