"""MCP servers exposing the workspace, sandbox and artifact store to agents.

Each server is a real Model Context Protocol server: it can be embedded
in-process or launched as a standalone stdio process that any MCP client
(Claude Desktop, other agents, `npx @modelcontextprotocol/inspector`) can use.

    python -m agentic.mcp_servers workspace --root /path/to/project
"""

from __future__ import annotations

from .artifacts_server import create_artifacts_server
from .sandbox import create_sandbox_server
from .workspace import create_workspace_server

__all__ = ["create_artifacts_server", "create_sandbox_server", "create_workspace_server"]
