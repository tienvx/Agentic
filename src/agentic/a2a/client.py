"""A2A client: discovery plus JSON-RPC calls over httpx."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from ..errors import A2AError, AgenticError, TaskNotFoundError
from .models import (
    AGENT_CARD_PATH,
    A2A_PROTOCOL_VERSION,
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
    text_part,
)

log = logging.getLogger(__name__)


class AgentEndpoint:
    """A resolved agent: its card plus the URL we actually call."""

    def __init__(self, card: AgentCard, base_url: str) -> None:
        self.card = card
        self.base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def skill_ids(self) -> list[str]:
        return [s.id for s in self.card.skills]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AgentEndpoint({self.name} @ {self.base_url})"


class A2AClient:
    """JSON-RPC 2.0 A2A client.

    ``base_url`` is the agent's root; the card is fetched from
    ``/.well-known/agent-card.json`` on first use.
    """

    def __init__(self, base_url: str, *, timeout: float = 300.0, headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._card: AgentCard | None = None
        self._headers = {"A2A-Version": A2A_PROTOCOL_VERSION, **(headers or {})}

    # -- discovery --------------------------------------------------------

    async def agent_card(self, *, refresh: bool = False) -> AgentCard:
        if self._card is not None and not refresh:
            return self._card
        async with httpx.AsyncClient(timeout=min(self.timeout, 20)) as client:
            response = await client.get(f"{self.base_url}{AGENT_CARD_PATH}", headers=self._headers)
        if response.status_code == 404:
            raise AgenticError(f"no agent card at {self.base_url}{AGENT_CARD_PATH}")
        response.raise_for_status()
        self._card = AgentCard.model_validate(response.json())
        return self._card

    # -- messaging --------------------------------------------------------

    async def send_text(
        self,
        text: str,
        *,
        context_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        return_immediately: bool = False,
    ) -> Task | Message:
        message = Message(
            role=Role.USER,
            parts=[text_part(text)],
            context_id=context_id,
            task_id=task_id,
        )
        return await self.send_message(message, metadata=metadata, return_immediately=return_immediately)

    async def send_message(
        self,
        message: Message,
        *,
        metadata: dict[str, Any] | None = None,
        return_immediately: bool = False,
    ) -> Task | Message:
        request = SendMessageRequest(
            message=message,
            configuration=SendMessageConfiguration(return_immediately=return_immediately)
            if return_immediately
            else None,
            metadata=metadata,
        )
        payload = await self._rpc("SendMessage", request.to_wire())
        if "status" in payload:
            return Task.model_validate(payload)
        return Message.model_validate(payload)

    async def stream_message(self, message: Message) -> AsyncIterator[StreamResponse]:
        """Server-Sent Events stream of StreamResponse frames."""
        request = SendMessageRequest(message=message)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.base_url + "/",
                json={
                    "jsonrpc": "2.0",
                    "id": uuid4().hex,
                    "method": "SendStreamingMessage",
                    "params": request.to_wire(),
                },
                headers={**self._headers, "Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise AgenticError(f"stream failed {response.status_code}: {body[:200]!r}")
                async for event in _iter_sse(response.aiter_text()):
                    if event.get("event") == "done":
                        break
                    data = event.get("data")
                    if not data:
                        continue
                    frame = json.loads(data)
                    if "error" in frame:
                        raise _materialise(frame["error"] or {})
                    # JSON-RPC binding wraps frames in an envelope; unwrap it.
                    payload = frame.get("result", frame)
                    yield StreamResponse.model_validate(payload)

    async def get_task(self, task_id: str) -> Task:
        payload = await self._rpc("GetTask", {"id": task_id})
        return Task.model_validate(payload)

    async def list_tasks(self, *, context_id: str | None = None, limit: int = 50) -> list[Task]:
        params: dict[str, Any] = {"pageSize": limit}
        if context_id:
            params["contextId"] = context_id
        payload = await self._rpc("ListTasks", params)
        return [Task.model_validate(t) for t in payload.get("tasks", [])]

    async def cancel_task(self, task_id: str) -> Task:
        payload = await self._rpc("CancelTask", {"id": task_id})
        return Task.model_validate(payload)

    async def wait_for_terminal(self, task_id: str, *, poll: float = 0.5, max_wait: float = 600.0) -> Task:
        import asyncio
        import time

        started = time.perf_counter()
        while time.perf_counter() - started < max_wait:
            task = await self.get_task(task_id)
            if task.status.state.is_terminal or task.status.state.is_interrupted:
                return task
            await asyncio.sleep(poll)
        raise AgenticError(f"task {task_id} did not settle within {max_wait}s")

    # -- transport --------------------------------------------------------

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "id": uuid4().hex, "method": method, "params": params}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.base_url + "/", json=body, headers=self._headers)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise AgenticError(f"agent returned non-JSON ({response.status_code}): {response.text[:200]}") from exc
        if "error" in payload:
            error = payload["error"] or {}
            raise _materialise(error)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise AgenticError(f"malformed result for {method}: {payload}")
        return result


def _materialise(error: dict[str, Any]) -> A2AError:
    from ..errors import A2A_ERROR_BY_NAME

    message = str(error.get("message", "unknown A2A error"))
    data = error.get("data")
    if isinstance(data, dict) and isinstance(data.get("errorName"), str):
        cls = A2A_ERROR_BY_NAME.get(data["errorName"])
        if cls:
            return cls(message, data)
    code = error.get("code")
    for cls in A2A_ERROR_BY_NAME.values():
        if cls.code == code:
            return cls(message, data)
    if code == -32001:
        return TaskNotFoundError(message, data)
    return A2AError(message, data)


async def _iter_sse(chunks: AsyncIterator[str]) -> AsyncIterator[dict[str, str]]:
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            event: dict[str, str] = {}
            for line in frame.splitlines():
                if line.startswith("event:"):
                    event["event"] = line[6:].strip()
                elif line.startswith("data:"):
                    event["data"] = (event.get("data", "") + line[5:].strip())
            if event:
                yield event


async def discover(base_url: str) -> AgentEndpoint:
    client = A2AClient(base_url)
    card = await client.agent_card()
    return AgentEndpoint(card, base_url)
