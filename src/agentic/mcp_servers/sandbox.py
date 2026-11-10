"""Sandbox MCP server: run builds and tests inside a project directory.

Commands are restricted to an allowlist of executable prefixes so an agent
cannot shell out arbitrarily. This is the tool that makes verification real
rather than a model's claim about what it thinks the tests did.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

DEFAULT_ALLOWLIST = (
    "pytest",
    "python",
    "python3",
    "uv",
    "ruff",
    "mypy",
    "black",
    "pip",
    "node",
    "npm",
    "npx",
    "cargo",
    "go",
    "ls",
    "cat",
    "true",
    "echo",
)

# Anything that could chain into an un-allowlisted program.
_SHELL_METACHAR_RE = re.compile(r"[;&|`$]|\n")


def create_sandbox_server(
    root: Path,
    *,
    allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST,
    timeout: float = 120.0,
) -> MCPServer:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    server = MCPServer(
        name="agentic-sandbox",
        version="1.0.0",
        instructions=(
            f"Run commands with cwd={root}. Only these executables are permitted: "
            f"{', '.join(allowlist)}. Shell metacharacters are rejected."
        ),
    )

    @server.tool(
        name="run_command",
        description=(
            "Run a whitelisted command in the project directory. Returns exit_code, stdout and stderr "
            "(each truncated). Use it to run the test suite or a syntax check."
        ),
    )
    async def run_command(command: str, timeout_seconds: float | None = None) -> dict:
        command = command.strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        if _SHELL_METACHAR_RE.search(command):
            return {"ok": False, "error": "shell metacharacters (; & | ` $ newline) are not permitted"}
        argv = command.split()
        program = Path(argv[0]).name
        if program not in allowlist:
            return {"ok": False, "error": f"executable {program!r} is not allowlisted"}
        if program in {"python", "python3"} and any(
            flag in argv for flag in ("-c", "--command", "-m", "pickle", "pty")
        ):
            return {"ok": False, "error": "python -c / -m are not permitted; use run_tests or a script file"}
        resolved = shutil.which(program)
        if not resolved:
            return {"ok": False, "error": f"executable {program!r} not found on PATH"}

        limit = min(float(timeout_seconds or timeout), 600.0)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_env(root),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=limit)
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": f"command timed out after {limit}s", "command": command}
        except OSError as exc:
            return {"ok": False, "error": f"failed to start command: {exc}"}

        return {
            "ok": proc.returncode == 0,
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", "replace")[-20_000:],
            "stderr": stderr.decode("utf-8", "replace")[-20_000:],
        }

    @server.tool(
        name="run_tests",
        description=(
            "Run the project's test suite and return a structured summary. "
            "framework is one of: pytest, npm-test, cargo-test, go-test."
        ),
    )
    async def run_tests(framework: str = "pytest", target: str = "") -> dict:
        if framework == "pytest":
            command = f"{sys.executable} -m pytest -q {target}".strip()
            # sys.executable is not allowlisted by name, so map it to the interpreter directly.
            argv = [sys.executable, "-m", "pytest", "-q"] + ([target] if target else [])
            return await _exec(argv, root, timeout)
        if framework == "npm-test":
            return await _exec(["npm", "test"], root, timeout)
        if framework == "cargo-test":
            return await _exec(["cargo", "test"], root, timeout)
        if framework == "go-test":
            return await _exec(["go", "test", "./..."], root, timeout)
        return {"ok": False, "error": f"unknown framework {framework!r}"}

    @server.tool(
        name="check_python_syntax",
        description=(
            "Parse every .py file in the project and report syntax errors with file and line. "
            "Run this before the test suite: it localises breakage far better than a collection error."
        ),
    )
    async def check_python_syntax(pattern: str = "**/*.py") -> dict:
        import ast

        problems: list[dict[str, Any]] = []
        checked = 0
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if any(part in {".git", "__pycache__", ".venv", ".pytest_cache"} for part in Path(rel).parts):
                continue
            checked += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except SyntaxError as exc:
                problems.append(
                    {
                        "path": rel,
                        "line": exc.lineno,
                        "offset": exc.offset,
                        "message": exc.msg,
                        "source": (exc.text or "").strip()[:200],
                    }
                )
            except OSError as exc:
                problems.append({"path": rel, "line": None, "message": f"unreadable: {exc}"})
            if len(problems) >= 25:
                break
        return {"ok": not problems, "checked": checked, "problems": problems}

    @server.tool(name="environment_info", description="Report interpreter and tool availability in the sandbox.")
    async def environment_info() -> dict:
        return {
            "root": str(root),
            "python": sys.version.split()[0],
            "available": {tool: bool(shutil.which(tool)) for tool in allowlist},
        }

    return server


async def _exec(argv: list[str], cwd: Path, timeout: float) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env(cwd)
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": f"timed out after {timeout}s", "command": " ".join(argv)}
    except OSError as exc:
        return {"ok": False, "error": f"failed to start: {exc}", "command": " ".join(argv)}
    return {
        "ok": proc.returncode == 0,
        "command": " ".join(argv),
        "exit_code": proc.returncode,
        "stdout": stdout.decode("utf-8", "replace")[-20_000:],
        "stderr": stderr.decode("utf-8", "replace")[-20_000:],
    }


def _env(root: Path) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env.pop("VIRTUAL_ENV", None)
    return env
