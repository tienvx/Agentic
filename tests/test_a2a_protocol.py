"""A2A protocol behaviour over a real socket: our client against our server."""

from __future__ import annotations

import json

import httpx
import pytest

from agentic.a2a.client import A2AClient
from agentic.a2a.models import Message, Role, TaskState, text_part
from agentic.errors import AgenticError, MethodNotFoundError, TaskNotFoundError

SCOUT = "/agents/scout"


def test_agent_card_is_discoverable(live_server: str) -> None:
    response = httpx.get(f"{live_server}{SCOUT}/.well-known/agent-card.json", timeout=20)
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Idea Scout"
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card["capabilities"]["streaming"] is True
    assert card["skills"][0]["id"] == "scout"


@pytest.mark.asyncio
async def test_send_message_produces_artifact(live_server: str) -> None:
    client = A2AClient(f"{live_server}{SCOUT}", timeout=120)
    result = await client.send_text("A tool that counts words in meeting notes")
    assert isinstance(result.id, str)
    assert result.status.state is TaskState.COMPLETED
    assert result.artifacts, "agent returned no artifact"
    payload = json.loads(result.artifacts[0].parts[0].as_text())
    assert payload["title"]
    assert payload["success_metrics"]


@pytest.mark.asyncio
async def test_get_and_list_tasks(live_server: str) -> None:
    client = A2AClient(f"{live_server}{SCOUT}", timeout=120)
    task = await client.send_text("A tool that formats currency amounts")
    fetched = await client.get_task(task.id)
    assert fetched.id == task.id
    assert fetched.status.state is TaskState.COMPLETED
    tasks = await client.list_tasks(limit=20)
    assert any(t.id == task.id for t in tasks)


@pytest.mark.asyncio
async def test_unknown_task_returns_a2a_error(live_server: str) -> None:
    client = A2AClient(f"{live_server}{SCOUT}", timeout=60)
    with pytest.raises(TaskNotFoundError):
        await client.get_task("does-not-exist")


@pytest.mark.asyncio
async def test_unknown_method_returns_jsonrpc_error(live_server: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{live_server}{SCOUT}/",
            json={"jsonrpc": "2.0", "id": "1", "method": "NoSuchMethod", "params": {}},
        )
    assert response.status_code == 200
    error = response.json()["error"]
    assert error["code"] == -32601


@pytest.mark.asyncio
async def test_missing_message_part_is_invalid_params(live_server: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{live_server}{SCOUT}/",
            json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {}},
        )
    assert response.json()["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_empty_parts_is_invalid_params(live_server: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{live_server}{SCOUT}/",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "SendMessage",
                "params": {"message": {"role": "ROLE_USER", "parts": []}},
            },
        )
    assert response.json()["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_streaming_yields_task_then_terminal(live_server: str) -> None:
    client = A2AClient(f"{live_server}{SCOUT}", timeout=120)
    message = Message(role=Role.USER, parts=[text_part("A tool that normalises text")])
    states: list[str] = []
    saw_task = False
    artifacts = 0
    async for event in client.stream_message(message):
        if event.task is not None:
            saw_task = True
            states.append(event.task.status.state.value)
        if event.status_update is not None:
            states.append(event.status_update.status.state.value)
        if event.artifact_update is not None:
            artifacts += 1
    assert saw_task, "stream must begin with the Task object"
    assert artifacts >= 1
    assert states[-1] == TaskState.COMPLETED.value


def test_rest_binding_message_send(live_server: str) -> None:
    payload = {
        "message": {"role": "ROLE_USER", "parts": [{"text": "A tool that parses key value pairs"}]},
    }
    response = httpx.post(f"{live_server}{SCOUT}/message:send", json=payload, timeout=120)
    assert response.status_code == 200
    task = response.json()
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"]


def test_rest_binding_get_task(live_server: str) -> None:
    payload = {"message": {"role": "ROLE_USER", "parts": [{"text": "A tool that clamps numbers"}]}}
    task = httpx.post(f"{live_server}{SCOUT}/message:send", json=payload, timeout=120).json()
    fetched = httpx.get(f"{live_server}{SCOUT}/tasks/{task['id']}", timeout=30)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == task["id"]


def test_rest_binding_unknown_task_404(live_server: str) -> None:
    assert httpx.get(f"{live_server}{SCOUT}/tasks/nope", timeout=30).status_code == 404


@pytest.mark.asyncio
async def test_agent_reports_failure_as_failed_task(live_server: str) -> None:
    """An agent that cannot satisfy its contract must fail the task, not crash."""
    client = A2AClient(f"{live_server}/agents/architect", timeout=120)
    result = await client.send_text("no upstream requirements supplied")
    assert result.status.state is TaskState.FAILED
    assert result.status.message is not None
