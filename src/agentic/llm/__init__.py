"""LLM abstraction: OpenAI-compatible HTTP client plus a deterministic mock."""

from __future__ import annotations

from .base import ChatMessage, LLMClient, LLMResponse, ToolCall, ToolSpec
from .mock import MockLLM
from .openai_compat import OpenAICompatLLM

__all__ = [
    "ChatMessage",
    "LLMClient",
    "LLMResponse",
    "MockLLM",
    "OpenAICompatLLM",
    "ToolCall",
    "ToolSpec",
]
