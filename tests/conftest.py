"""Shared fixtures: a live agentic service on a real port."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """Boot `agentic serve` with the mock model and wait until it answers."""
    port = _free_port()
    env = {
        **os.environ,
        "AGENTIC_LLM_MODE": "mock",
        "AGENTIC_HOME": str(REPO / ".agentic-test"),
        "PYTHONPATH": str(SRC),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "agentic", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 45
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"server exited early ({process.returncode}):\n{output[-3000:]}")
            try:
                if httpx.get(f"{base}/health", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError("server did not become healthy in time")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
