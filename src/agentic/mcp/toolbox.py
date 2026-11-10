"""MCP toolbox: spawn stdio MCP servers and call their tools.

Agents never touch the filesystem or a shell directly — they go through MCP
tools. That keeps every side effect observable, policy-controlled and swappable
for a remote server without changing agent code.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..errors import ToolError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerSpec:
    """How to launch one MCP server."""

    key: str
    module: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def workspace(cls, root: Path, *, read_only: bool = False) -> "ServerSpec":
        args = ["workspace", "--root", str(root)]
        if read_only:
            args.append("--read-only")
        return cls(key="workspace", module="agentic.mcp_servers", args=args)

    @classmethod
    def sandbox(cls, root: Path, *, timeout: float = 120.0) -> "ServerSpec":
        return cls(key="sandbox", module="agentic.mcp_servers", args=["sandbox", "--root", str(root), "--timeout", str(timeout)])

    @classmethod
    def artifacts(cls, run_dir: Path, run_id: str) -> "ServerSpec":
        return cls(
            key="artifacts",
            module="agentic.mcp_servers",
            args=["artifacts", "--run-dir", str(run_dir), "--run-id", run_id],
        )


class MCPCallError(ToolError):
    """A tool call returned an error payload."""


class MCPToolbox:
    """Owns the stdio MCP server processes for one agent session."""

    def __init__(self, specs: list[ServerSpec], *, enabled: bool = True) -> None:
        self.specs = specs
        self.enabled = enabled
        self._sessions: dict[str, ClientSession] = {}
        self._exits: list[Any] = []
        self._tool_names: dict[str, list[str]] = {}
        self._started = False

    async def __aenter__(self) -> "MCPToolbox":
        if not self.enabled:
            return self
        for spec in self.specs:
            env = {**os.environ, "PYTHONPATH": _pythonpath(), **spec.env}
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", spec.module, *spec.args],
                env=env,
            )
            read, write = await self._enter(stdio_client(params))
            session = ClientSession(read, write)
            await self._enter(session)
            await session.initialize()
            listing = await session.list_tools()
            self._sessions[spec.key] = session
            self._tool_names[spec.key] = [t.name for t in listing.tools]
            log.debug("MCP server %s ready: %s", spec.key, self._tool_names[spec.key])
        self._started = True
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        for exit_ in reversed(self._exits):
            with contextlib.suppress(Exception):
                await exit_(*exc_info)
        self._exits.clear()
        self._sessions.clear()
        self._started = False

    async def _enter(self, cm: Any) -> Any:
        value = await cm.__aenter__()
        self._exits.append(cm.__aexit__)
        return value

    # -- introspection ----------------------------------------------------

    @property
    def servers(self) -> list[str]:
        return sorted(self._tool_names)

    def tools_for(self, server: str) -> list[str]:
        return list(self._tool_names.get(server, []))

    def has(self, server: str, tool: str) -> bool:
        return tool in self._tool_names.get(server, [])

    # -- calls ------------------------------------------------------------

    async def call(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self._sessions.get(server)
        if session is None:
            raise ToolError(f"MCP server {server!r} is not running (started={self._started})")
        try:
            result = await session.call_tool(tool, arguments or {})
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"{server}.{tool} raised {type(exc).__name__}: {exc}") from exc

        payload = _extract(result)
        if getattr(result, "isError", False):
            raise MCPCallError(f"{server}.{tool} failed: {payload}")
        return payload


def _extract(result: Any) -> dict[str, Any]:
    """Normalise a CallToolResult into a plain dict."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    chunks: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    joined = "\n".join(chunks).strip()
    if joined:
        try:
            parsed = json.loads(joined)
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            return {"text": joined}
    return {}


def _pythonpath() -> str:
    """Ensure the agentic package is importable by stdio child processes."""
    import agentic

    package_root = str(Path(agentic.__file__).resolve().parents[1])
    existing = os.environ.get("PYTHONPATH", "")
    if package_root in existing.split(os.pathsep):
        return existing
    return f"{package_root}{os.pathsep}{existing}" if existing else package_root
