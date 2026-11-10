"""Launch an agentic MCP server over stdio.

    python -m agentic.mcp_servers workspace --root /path/to/project [--read-only]
    python -m agentic.mcp_servers sandbox   --root /path/to/project
    python -m agentic.mcp_servers artifacts --run-dir /path/to/run --run-id abc123
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-mcp", description="Run an agentic MCP server over stdio")
    sub = parser.add_subparsers(dest="server", required=True)

    ws = sub.add_parser("workspace", help="sandboxed filesystem tools")
    ws.add_argument("--root", required=True, type=Path)
    ws.add_argument("--read-only", action="store_true")

    sb = sub.add_parser("sandbox", help="run builds and tests")
    sb.add_argument("--root", required=True, type=Path)
    sb.add_argument("--timeout", type=float, default=120.0)

    ar = sub.add_parser("artifacts", help="content-addressed artifact store")
    ar.add_argument("--run-dir", required=True, type=Path)
    ar.add_argument("--run-id", required=True)

    args = parser.parse_args(argv)

    if args.server == "workspace":
        from .workspace import create_workspace_server

        server = create_workspace_server(args.root, read_only=args.read_only)
    elif args.server == "sandbox":
        from .sandbox import create_sandbox_server

        server = create_sandbox_server(args.root, timeout=args.timeout)
    else:
        from .artifacts_server import create_artifacts_server, store_from_dir

        server = create_artifacts_server(store_from_dir(args.run_dir, args.run_id))

    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
