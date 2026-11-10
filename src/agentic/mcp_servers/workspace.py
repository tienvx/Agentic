"""Workspace MCP server: sandboxed filesystem access for a single project."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules", ".mypy_cache", ".agentic"}


def _safe_join(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root`` or raise. Blocks traversal escapes."""
    if not relative or relative.startswith(("/", "~")):
        raise ValueError(f"path must be relative to the workspace root: {relative!r}")
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path escapes the workspace root: {relative!r}")
    return candidate


@lru_cache(maxsize=64)
def _glob_re(pattern: str) -> re.Pattern[str]:
    """Translate a glob (with real ``**`` support) into a compiled regex."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(out) + "$")


def _matches(relative: str, pattern: str) -> bool:
    if pattern in ("", "*", "**", "**/*"):
        return True
    if _glob_re(pattern).match(relative):
        return True
    # A bare pattern like "*.py" should match at any depth.
    if "/" not in pattern:
        return _glob_re(pattern).match(Path(relative).name) is not None
    return False


def create_workspace_server(root: Path, *, read_only: bool = False) -> MCPServer:
    """Build an MCP server whose tools are confined to ``root``."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    mode = "read-only" if read_only else "read-write"
    server = MCPServer(
        name="agentic-workspace",
        version="1.0.0",
        instructions=(
            f"Filesystem tools scoped to {root}. All paths are relative to that root. "
            f"Mode: {mode}. Write files with write_file; never use absolute paths."
        ),
    )

    @server.tool(
        name="list_files",
        description="List files in the workspace as paths relative to the root, honouring an optional glob.",
    )
    async def list_files(pattern: str = "**/*") -> dict:
        matches: list[dict] = []
        for path in sorted(root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in IGNORED_DIRS for part in Path(rel).parts):
                continue
            if not _matches(rel, pattern):
                continue
            matches.append({"path": rel, "size": path.stat().st_size})
            if len(matches) >= 500:
                break
        return {"root": str(root), "count": len(matches), "files": matches}

    @server.tool(name="read_file", description="Read a UTF-8 text file from the workspace.")
    async def read_file(path: str, max_bytes: int = 200_000) -> dict:
        try:
            target = _safe_join(root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not target.is_file():
            return {"ok": False, "error": f"not a file: {path}"}
        data = target.read_bytes()[:max_bytes]
        return {"ok": True, "path": path, "size": target.stat().st_size, "content": data.decode("utf-8", "replace")}

    @server.tool(name="write_file", description="Create or overwrite a UTF-8 text file in the workspace.")
    async def write_file(path: str, content: str, append: bool = False) -> dict:
        if read_only:
            return {"ok": False, "error": "workspace server is read-only"}
        try:
            target = _safe_join(root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(content)
        return {"ok": True, "path": path, "bytes": len(content.encode())}

    @server.tool(name="delete_file", description="Delete a file from the workspace.")
    async def delete_file(path: str) -> dict:
        if read_only:
            return {"ok": False, "error": "workspace server is read-only"}
        try:
            target = _safe_join(root, path)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not target.is_file():
            return {"ok": False, "error": f"not a file: {path}"}
        target.unlink()
        return {"ok": True, "path": path, "deleted": True}

    @server.tool(name="workspace_info", description="Report the workspace root and whether writes are allowed.")
    async def workspace_info() -> dict:
        return {"root": str(root), "read_only": read_only, "exists": root.is_dir()}

    return server
