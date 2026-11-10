"""A2A server: JSON-RPC 2.0 and HTTP+JSON/REST bindings with SSE streaming.

Exposes the endpoints mandated by A2A v1.0.0 sections 9 and 11:

  GET  /.well-known/agent-card.json
  POST /                      (JSON-RPC 2.0)
  POST /message:send          POST /message:stream
  GET  /tasks                 GET  /tasks/{id}
  POST /tasks/{id}:cancel     POST /tasks/{id}:subscribe
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..errors import (
    A2AError,
    InvalidParamsError,
    MethodNotFoundError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from .models import (
    AGENT_CARD_PATH,
    Artifact,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    data_part,
)

log = logging.getLogger(__name__)

SUPPORTED_METHODS = {
    "SendMessage",
    "SendStreamingMessage",
    "GetTask",
    "ListTasks",
    "CancelTask",
    "SubscribeToTask",
    "GetExtendedAgentCard",
}


class TaskContext:
    """Handle passed to an agent implementation while it works on a task."""

    def __init__(self, task: Task, bus: asyncio.Queue[StreamResponse | None]) -> None:
        self.task = task
        self._bus = bus
        self.cancelled = False

    async def set_state(self, state: TaskState, text: str = "") -> None:
        self.task.status = TaskStatus(
            state=state,
            message=_agent_message(text, self.task.context_id, self.task.id) if text else None,
        )
        await self._publish(StreamResponse(status_update=TaskStatusUpdateEvent(
            task_id=self.task.id, context_id=self.task.context_id or "", status=self.task.status
        )))

    async def working(self, text: str = "") -> None:
        await self.set_state(TaskState.WORKING, text)

    async def artifact(self, name: str, payload: Any, *, description: str = "") -> Artifact:
        art = Artifact(name=name, description=description or name, parts=[data_part(payload)])
        self.task.artifacts.append(art)
        await self._publish(StreamResponse(artifact_update=TaskArtifactUpdateEvent(
            task_id=self.task.id, context_id=self.task.context_id or "", artifact=art, last_chunk=True
        )))
        return art

    async def complete(self, text: str = "") -> None:
        await self.set_state(TaskState.COMPLETED, text)

    async def fail(self, text: str = "") -> None:
        await self.set_state(TaskState.FAILED, text)

    async def input_required(self, text: str = "") -> None:
        await self.set_state(TaskState.INPUT_REQUIRED, text)

    async def _publish(self, event: StreamResponse) -> None:
        await self._bus.put(event)


def _agent_message(text: str, context_id: str | None, task_id: str | None) -> Message:
    return Message(role=Role.AGENT, parts=[Part(text=text)], context_id=context_id, task_id=task_id)


AgentHandler = Callable[[TaskContext, Message], Awaitable[None]]


class A2AHandler:
    """In-memory task manager plus the agent callback."""

    def __init__(self, handler: AgentHandler) -> None:
        self._handler = handler
        self._tasks: dict[str, Task] = {}
        self._buses: dict[str, asyncio.Queue[StreamResponse | None]] = {}
        self._handles: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    # -- task lifecycle ---------------------------------------------------

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"no task with id {task_id!r}")
        return task

    def list(
        self, *, context_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Task]:
        tasks = list(self._tasks.values())
        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if status:
            tasks = [t for t in tasks if t.status.state.value == status]
        tasks.sort(key=lambda t: t.status.timestamp, reverse=True)
        return tasks[: max(1, min(limit, 200))]

    async def start(self, request: SendMessageRequest) -> tuple[Task, asyncio.Queue[StreamResponse | None]]:
        message = request.message
        task_id = message.task_id or f"task-{uuid4().hex[:12]}"
        context_id = message.context_id or f"ctx-{uuid4().hex[:12]}"
        if message.task_id:
            existing = self.get(message.task_id)
            if existing.status.state.is_terminal:
                raise UnsupportedOperationError(
                    f"task {message.task_id} is in terminal state {existing.status.state.value}"
                )
            task = existing
        else:
            task = Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.SUBMITTED),
                history=[message],
            )
            self._tasks[task_id] = task

        bus: asyncio.Queue[StreamResponse | None] = self._buses.get(task_id) or asyncio.Queue()
        self._buses[task_id] = bus
        await bus.put(StreamResponse(task=task))

        context = TaskContext(task, bus)
        runner = asyncio.create_task(self._run(context, message, bus))
        self._handles[task_id] = runner
        if request.configuration and request.configuration.return_immediately:
            return task, bus
        # Blocking: wait for the terminal event (spec 3.2.2).
        await self._await_terminal(runner, bus)
        return task, bus

    async def _await_terminal(self, runner: asyncio.Task[None], bus: asyncio.Queue) -> None:
        try:
            await asyncio.wait_for(runner, timeout=None)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - recorded on the task status
            pass

    async def _run(self, context: TaskContext, message: Message, bus: asyncio.Queue) -> None:
        task = context.task
        try:
            await context.working()
            await self._handler(context, message)
            if not task.status.state.is_terminal and not task.status.state.is_interrupted:
                await context.complete()
        except asyncio.CancelledError:
            context.cancelled = True
            await context.set_state(TaskState.CANCELED, "canceled")
            raise
        except A2AError as exc:
            await context.fail(exc.message)
        except Exception as exc:  # noqa: BLE001 - surface as a failed task
            log.exception("agent handler failed")
            await context.fail(f"{type(exc).__name__}: {exc}")
        finally:
            await bus.put(None)

    async def cancel(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status.state.is_terminal:
            raise TaskNotCancelableError(f"task {task_id} already {task.status.state.value}")
        handle = self._handles.get(task_id)
        if handle and not handle.done():
            handle.cancel()
        task.status = TaskStatus(state=TaskState.CANCELED)
        return task

    async def stream(self, task_id: str) -> AsyncIterator[StreamResponse]:
        task = self.get(task_id)
        if task.status.state.is_terminal:
            raise UnsupportedOperationError(
                f"task {task_id} is terminal ({task.status.state.value}); cannot subscribe"
            )
        bus = self._buses.get(task_id)
        if bus is None:
            return
        while True:
            event = await bus.get()
            if event is None:
                break
            yield event


class A2AServer:
    """Mounts an :class:`A2AHandler` as a FastAPI app."""

    def __init__(self, *, card: Any, handler: AgentHandler, jsonrpc_path: str = "/") -> None:
        self.card = card
        self.handler = A2AHandler(handler)
        self.jsonrpc_path = jsonrpc_path
        self.app = self._build_app()

    # -- app --------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        app = FastAPI(
            title=f"{self.card.name} (A2A {self.card.supported_interfaces[0].protocol_version})",
            version=self.card.version,
            docs_url="/docs",
            openapi_url="/openapi.json",
        )

        @app.get(AGENT_CARD_PATH, include_in_schema=False)
        async def agent_card(request: Request) -> JSONResponse:
            """The card is rendered per-request so its URL always matches where
            it was actually served from (host, port and mount path)."""
            card = self.card.model_copy(deep=True)
            full = str(request.url).rstrip("/")
            if full.endswith(AGENT_CARD_PATH):
                base = full[: -len(AGENT_CARD_PATH)]
            else:  # pragma: no cover - defensive
                base = str(request.base_url).rstrip("/")
            endpoint = f"{base}/"
            for interface in card.supported_interfaces:
                interface.url = endpoint
            return JSONResponse(card.to_wire())

        @app.exception_handler(A2AError)
        async def a2a_exception_handler(request: Request, exc: A2AError) -> JSONResponse:
            """REST binding: map A2A errors to the HTTP statuses from spec 5.4."""
            return JSONResponse(
                {"error": {"code": exc.code, "message": exc.message, "errorName": exc.error_name}},
                status_code=exc.http_status,
            )

        @app.post(self.jsonrpc_path, include_in_schema=False)
        async def rpc(request: Request) -> JSONResponse:
            return await self._handle_rpc(request)

        # HTTP+JSON/REST binding (spec section 11)
        @app.post("/message:send")
        async def rest_send(payload: dict) -> JSONResponse:
            return JSONResponse(await self._send(payload))

        @app.post("/message:stream")
        async def rest_stream(payload: dict) -> StreamingResponse:
            return self._stream_response(payload)

        @app.get("/tasks")
        async def rest_list(contextId: str | None = None, status: str | None = None, pageSize: int = 50) -> JSONResponse:
            tasks = self.handler.list(context_id=contextId, status=status, limit=pageSize)
            return JSONResponse({"tasks": [t.to_wire() for t in tasks], "nextPageToken": ""})

        @app.get("/tasks/{task_id}")
        async def rest_get(task_id: str) -> JSONResponse:
            return JSONResponse(self.handler.get(task_id).to_wire())

        @app.post("/tasks/{task_id}:cancel")
        async def rest_cancel(task_id: str) -> JSONResponse:
            return JSONResponse((await self.handler.cancel(task_id)).to_wire())

        @app.post("/tasks/{task_id}:subscribe")
        async def rest_subscribe(task_id: str) -> StreamingResponse:
            return self._sse(self.handler.stream(task_id))

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "agent": self.card.name}

        return app

    # -- JSON-RPC ---------------------------------------------------------

    async def _handle_rpc(self, request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return self._rpc_error(None, InvalidParamsError("request body is not valid JSON"))
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
            return self._rpc_error(body.get("id") if isinstance(body, dict) else None,
                                   InvalidParamsError("expected a JSON-RPC 2.0 object request"))
        rpc_id = body.get("id")
        method = body["method"]
        params = body.get("params") or {}
        if method not in SUPPORTED_METHODS:
            return self._rpc_error(rpc_id, MethodNotFoundError(f"unknown A2A method {method!r}"))
        if method == "SendStreamingMessage":
            return self._stream_rpc(rpc_id, params)
        try:
            result = await self._dispatch(method, params)
        except A2AError as exc:
            return self._rpc_error(rpc_id, exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("A2A method %s failed", method)
            return self._rpc_error(rpc_id, A2AError(f"{type(exc).__name__}: {exc}"))
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    async def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "SendMessage":
            return await self._send(params)
        if method == "GetTask":
            return self.handler.get(_require(params, "id" if "id" in params else "taskId")).to_wire()
        if method == "ListTasks":
            tasks = self.handler.list(
                context_id=params.get("contextId"),
                status=params.get("status"),
                limit=int(params.get("pageSize", 50) or 50),
            )
            return {"tasks": [t.to_wire() for t in tasks], "nextPageToken": ""}
        if method == "CancelTask":
            return (await self.handler.cancel(_require(params, "id" if "id" in params else "taskId"))).to_wire()
        if method == "GetExtendedAgentCard":
            raise UnsupportedOperationError("this agent publishes a single public card")
        raise MethodNotFoundError(method)

    async def _send(self, params: dict[str, Any]) -> dict[str, Any]:
        request = _parse_send_request(params)
        task, _ = await self.handler.start(request)
        return task.to_wire()

    # -- streaming --------------------------------------------------------

    def _stream_rpc(self, rpc_id: Any, params: dict[str, Any]) -> StreamingResponse:
        try:
            request = _parse_send_request(params)
        except A2AError as exc:
            return self._sse(_error_stream(exc), rpc_id=rpc_id)
        return self._sse(self._stream_task(request), rpc_id=rpc_id)

    async def _stream_task(self, request: SendMessageRequest) -> AsyncIterator[StreamResponse]:
        task, bus = await self.handler.start(request)
        yield StreamResponse(task=task)
        while True:
            event = await bus.get()
            if event is None:
                break
            yield event

    def _stream_response(self, payload: dict[str, Any]) -> StreamingResponse:
        try:
            request = _parse_send_request(payload)
        except A2AError as exc:
            return self._sse(_error_stream(exc))
        return self._sse(self._stream_task(request))

    def _sse(self, source: AsyncIterator[Any], *, rpc_id: Any = None) -> StreamingResponse:
        """SSE frames.

        The JSON-RPC binding wraps every frame in a JSON-RPC 2.0 response
        envelope (spec 9.4.2); the HTTP+JSON binding emits bare StreamResponse
        objects. ``rpc_id`` being set selects the JSON-RPC form.
        """

        async def frames() -> AsyncIterator[str]:
            async for event in source:
                payload = event.to_wire() if hasattr(event, "to_wire") else event
                if rpc_id is not None:
                    if "error" in payload:
                        body = {"jsonrpc": "2.0", "id": rpc_id, "error": payload["error"]}
                    else:
                        body = {"jsonrpc": "2.0", "id": rpc_id, "result": payload}
                else:
                    body = payload
                yield f"event: message\ndata: {json.dumps(body, sort_keys=True)}\n\n"
            # No sentinel frame: an empty JSON object is a *malformed* JSON-RPC
            # response, and strict clients (the official SDK) reject it. The
            # stream simply ends after the terminal task event.

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @staticmethod
    def _rpc_error(rpc_id: Any, error: A2AError) -> JSONResponse:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": rpc_id, "error": error.to_jsonrpc()},
            status_code=200,  # JSON-RPC carries errors in the envelope, not the status line
        )


async def _error_stream(exc: A2AError) -> AsyncIterator[dict[str, Any]]:
    yield {"error": exc.to_jsonrpc()}


def _require(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not value:
        raise InvalidParamsError(f"missing required parameter {key!r}")
    return str(value)


def _parse_send_request(params: dict[str, Any]) -> SendMessageRequest:
    message = params.get("message")
    if not isinstance(message, dict):
        raise InvalidParamsError("SendMessage requires a 'message' object")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise InvalidParamsError("message requires a non-empty 'parts' array")
    try:
        return SendMessageRequest(
            tenant=params.get("tenant"),
            message=Message.model_validate(message),
            configuration=(
                SendMessageConfiguration.model_validate(params["configuration"])
                if isinstance(params.get("configuration"), dict)
                else None
            ),
            metadata=params.get("metadata") if isinstance(params.get("metadata"), dict) else None,
        )
    except Exception as exc:  # noqa: BLE001
        raise InvalidParamsError(f"malformed SendMessageRequest: {exc}") from exc
