"""agentic — a multi-agent software factory built entirely on open standards.

Standards used:
  * A2A v1.0.0        agent discovery + task lifecycle (JSON-RPC 2.0 / HTTP+JSON / SSE)
  * MCP               tool and context access for agents (stdio + streamable HTTP)
  * JSON Schema 2020-12  machine-checkable contracts for every artifact
  * OpenAPI 3.1       the orchestrator's own HTTP surface
  * AGENTS.md         repo-level instructions for any agent that opens the tree
"""

from __future__ import annotations

__version__ = "0.1.0"

A2A_VERSION = "1.0"
MCP_PROTOCOL_VERSION = "2025-06-18"

__all__ = ["__version__", "A2A_VERSION", "MCP_PROTOCOL_VERSION"]
