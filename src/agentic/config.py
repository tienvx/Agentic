"""Configuration, loaded from environment variables and ``.env``.

Everything is prefixed ``AGENTIC_``. The single most important knob is
``AGENTIC_LLM_MODE``:

  auto   use a real endpoint if ``AGENTIC_LLM_BASE_URL`` is set, else mock
  mock   deterministic offline generator, no network, no keys
  openai force the OpenAI-compatible HTTP client
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values

from .errors import ConfigError

LLMMode = Literal["auto", "mock", "openai"]

_TRUE = {"1", "true", "yes", "on"}


def _repo_root() -> Path:
    """Best-effort location of the agentic checkout itself."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


class Settings:
    """Runtime configuration for a single process."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        raw: dict[str, str] = {}
        for candidate in (Path.cwd() / ".env", _repo_root() / ".env"):
            if candidate.is_file():
                raw.update({k: v for k, v in dotenv_values(candidate).items() if v is not None})
        if env:
            raw.update(env)
        raw.update({k: v for k, v in os.environ.items() if k.startswith("AGENTIC_")})

        def get(key: str, default: str = "") -> str:
            return raw.get(f"AGENTIC_{key}", default).strip()

        def flag(key: str, default: bool = False) -> bool:
            value = get(key)
            return default if not value else value.lower() in _TRUE

        self.llm_mode: LLMMode = get("LLM_MODE", "auto")  # type: ignore[assignment]
        if self.llm_mode not in ("auto", "mock", "openai"):
            raise ConfigError(f"AGENTIC_LLM_MODE must be auto|mock|openai, got {self.llm_mode!r}")

        self.base_url: str = get("LLM_BASE_URL", "").rstrip("/")
        self.api_key: str = get("LLM_API_KEY", "")
        self.model: str = get("MODEL", "qwen3-32b")
        self.temperature: float = float(get("LLM_TEMPERATURE", "0.2") or 0.2)
        self.max_tokens: int = int(get("LLM_MAX_TOKENS", "4096") or 4096)
        self.timeout: float = float(get("LLM_TIMEOUT", "180") or 180)
        self.repair_attempts: int = int(get("REPAIR_ATTEMPTS", "2") or 2)

        # Force mock when no endpoint is reachable and mode is auto.
        if self.llm_mode == "auto":
            self.llm_mode = "openai" if self.base_url else "mock"

        home = Path(get("HOME", "") or (Path.cwd() / ".agentic"))
        self.home: Path = Path(home).expanduser().resolve()
        self.runs_dir: Path = self.home / "runs"
        self.cache_dir: Path = self.home / "cache"

        self.max_fix_rounds: int = int(get("MAX_FIX_ROUNDS", "3") or 3)
        self.max_parallel_tasks: int = int(get("MAX_PARALLEL_TASKS", "1") or 1)
        self.enable_mcp: bool = flag("MCP", True)
        self.default_port: int = int(get("PORT", "8080") or 8080)
        self.default_host: str = get("HOST", "127.0.0.1") or "127.0.0.1"

    @property
    def is_mock(self) -> bool:
        return self.llm_mode == "mock"

    def describe(self) -> dict[str, object]:
        return {
            "llm_mode": self.llm_mode,
            "model": self.model,
            "base_url": self.base_url or None,
            "api_key_set": bool(self.api_key),
            "home": str(self.home),
            "max_fix_rounds": self.max_fix_rounds,
            "mcp_enabled": self.enable_mcp,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Settings(mode={self.llm_mode}, model={self.model!r}, home={self.home})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
