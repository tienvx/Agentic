"""Drive agentic's A2A server with the *official* a2a-sdk client.

If this passes, any A2A-compliant client in any language can use these agents —
we are not merely claiming to implement the spec, we are interoperating with
the reference implementation.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("a2a.client")
json_format = pytest.importorskip("google.protobuf.json_format")

from a2a.client import A2ACardResolver, ClientFactory  # noqa: E402
from a2a.types import a2a_pb2 as pb  # noqa: E402

from agentic.a2a.models import TaskState  # noqa: E402

SCOUT = "/agents/scout"


def _request(text: str) -> pb.SendMessageRequest:
    return pb.SendMessageRequest(
        message=pb.Message(
            message_id="official-client-1",
            role=pb.Role.ROLE_USER,
            parts=[pb.Part(text=text)],
        )
    )


@pytest.mark.asyncio
async def test_official_resolver_reads_our_card(live_server: str) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=30) as http:
        resolver = A2ACardResolver(http, f"{live_server}{SCOUT}")
        card = await resolver.get_agent_card()
    assert card.name == "Idea Scout"
    assert card.skills[0].id == "scout"
    assert card.supported_interfaces[0].protocol_version == "1.0"


@pytest.mark.asyncio
async def test_official_client_sends_message(live_server: str) -> None:
    factory = ClientFactory()
    client = factory.create_from_url(f"{live_server}{SCOUT}")
    if inspect.isawaitable(client):
        client = await client

    final_state = None
    artifact_names: list[str] = []
    async for response in client.send_message(_request("A tool that counts words in notes")):
        which = response.WhichOneof("payload")
        if which == "task":
            final_state = response.task.status.state
        elif which == "status_update":
            final_state = response.status_update.status.state
        elif which == "artifact_update":
            artifact_names.append(response.artifact_update.artifact.name)

    assert final_state == pb.TaskState.TASK_STATE_COMPLETED
    assert "IdeaBrief" in artifact_names
    await client.close()


@pytest.mark.asyncio
async def test_official_client_reads_our_artifact_payload(live_server: str) -> None:
    factory = ClientFactory()
    client = factory.create_from_url(f"{live_server}{SCOUT}")
    if inspect.isawaitable(client):
        client = await client

    brief = None
    async for response in client.send_message(_request("A tool that totals invoice line items")):
        if response.WhichOneof("payload") == "artifact_update":
            part = response.artifact_update.artifact.parts[0]
            brief = json_format.MessageToDict(part.data)

    assert brief is not None
    payload = brief.get("structValue", brief)
    assert payload.get("title")
    assert "success_metrics" in payload
    await client.close()


@pytest.mark.asyncio
async def test_official_client_gets_task(live_server: str) -> None:
    factory = ClientFactory()
    client = factory.create_from_url(f"{live_server}{SCOUT}")
    if inspect.isawaitable(client):
        client = await client

    task_id = None
    async for response in client.send_message(_request("A tool that masks secrets")):
        if response.WhichOneof("payload") == "task":
            task_id = response.task.id

    assert task_id
    fetched = await client.get_task(pb.GetTaskRequest(id=task_id))
    assert fetched.id == task_id
    assert fetched.status.state == pb.TaskState.TASK_STATE_COMPLETED
    await client.close()
