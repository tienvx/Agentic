"""Artifacts MCP server: read and write the run's content-addressed artifacts."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from ..core.artifacts import ArtifactStore
from ..errors import ContractError


def create_artifacts_server(store: ArtifactStore) -> MCPServer:
    server = MCPServer(
        name="agentic-artifacts",
        version="1.0.0",
        instructions=(
            f"Artifacts for run {store.run_id}. Names are IdeaBrief, Requirements, Architecture, "
            "TaskPlan, BuildResult, TestReport, Review. Writes are JSON-Schema validated."
        ),
    )

    @server.tool(name="list_artifacts", description="List artifact names available in this run.")
    async def list_artifacts() -> dict:
        names = store.list_names()
        return {"run_id": store.run_id, "count": len(names), "artifacts": names}

    @server.tool(name="read_artifact", description="Read an artifact by name or agentic:// URI.")
    async def read_artifact(name: str) -> dict:
        try:
            return {"ok": True, "name": name, "payload": store.get_json(name)}
        except ContractError as exc:
            return {"ok": False, "error": str(exc)}

    @server.tool(
        name="write_artifact",
        description="Store a JSON artifact. Validated against its published JSON Schema before acceptance.",
    )
    async def write_artifact(name: str, payload: dict, validate: bool = True) -> dict:
        try:
            stored = store.put_json(name, payload, validate=validate)
        except ContractError as exc:
            return {"ok": False, "error": str(exc), "details": getattr(exc, "errors", [])}
        return {"ok": True, "uri": stored.uri, "digest": stored.digest[:16], "bytes": stored.size}

    @server.tool(name="project_path", description="Absolute path of the project directory for this run.")
    async def project_path() -> dict:
        return {"project_dir": str(store.project_dir), "run_dir": str(store.run_dir)}

    return server


def store_from_dir(run_dir: Path, run_id: str) -> ArtifactStore:
    return ArtifactStore(Path(run_dir), run_id)
