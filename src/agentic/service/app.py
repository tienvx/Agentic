"""The agentic HTTP service.

Two standards-compliant surfaces on one port:

  * An OpenAPI 3.1 REST API for driving runs (``/api/*``), auto-documented at
    ``/docs``.
  * A full A2A v1.0.0 endpoint per agent (``/agents/<stage>/``), each publishing
    an Agent Card at ``/.well-known/agent-card.json`` and speaking JSON-RPC 2.0
    with SSE streaming. Any A2A client can drive them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..a2a.models import AgentCard, Message, Task, TaskState, data_part, text_part
from ..a2a.server import A2AServer, TaskContext
from ..agents.registry import BY_STAGE, catalogue
from ..config import Settings, get_settings
from ..core.events import Event, EventBus
from ..llm.base import LLMClient
from ..pipeline.orchestrator import Orchestrator, default_llm

log = logging.getLogger(__name__)


class RunRequest(BaseModel):
    idea: str = Field(min_length=8, description="The software idea, in plain language.")
    max_fix_rounds: int | None = Field(default=None, ge=0, le=10)
    use_mcp: bool | None = None


class RunSummary(BaseModel):
    run_id: str
    idea: str
    status: str
    tests_passed: int = 0
    tests_failed: int = 0
    files: int = 0
    project_dir: str = ""


@dataclass
class RunHandle:
    run_id: str
    idea: str
    status: str = "queued"
    events: EventBus = field(default_factory=EventBus)
    outcome: Any | None = None
    error: str = ""
    task: asyncio.Task[None] | None = None


class RunRegistry:
    """In-process run tracker."""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._lock = asyncio.Lock()

    def create(self, idea: str) -> RunHandle:
        handle = RunHandle(run_id=f"run-{uuid4().hex[:10]}", idea=idea)
        self._runs[handle.run_id] = handle
        return handle

    def get(self, run_id: str) -> RunHandle:
        handle = self._runs.get(run_id)
        if handle is None:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
        return handle

    def list(self) -> list[RunHandle]:
        return list(self._runs.values())

    async def start(self, handle: RunHandle, request: RunRequest, settings: Settings, llm: LLMClient) -> None:
        async with self._lock:
            orchestrator = Orchestrator(
                llm=llm,
                settings=settings,
                events=handle.events,
                run_id=handle.run_id,
                use_mcp=request.use_mcp,
            )
            handle.status = "running"

            async def runner() -> None:
                try:
                    handle.outcome = await orchestrator.build(handle.idea, max_fix_rounds=request.max_fix_rounds)
                    handle.status = handle.outcome.report.status
                except Exception as exc:  # noqa: BLE001
                    log.exception("run %s crashed", handle.run_id)
                    handle.status = "failed"
                    handle.error = f"{type(exc).__name__}: {exc}"

            handle.task = asyncio.create_task(runner())


def create_app(
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    enable_a2a: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or default_llm(settings)
    registry = RunRegistry()
    resolved_llm = llm

    app = FastAPI(
        title="agentic",
        version=__version__,
        description=(
            "A multi-agent software factory. Idea -> requirements -> architecture -> plan -> code -> "
            "tests -> review, with every agent speaking A2A and every tool exposed over MCP."
        ),
        contact={"name": "agentic", "url": "https://github.com/agentic"},
        license_info={"name": "MIT"},
    )

    # -- health & discovery ------------------------------------------------

    @app.get("/health", tags=["service"])
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "llm": settings.describe()}

    @app.get("/api/agents", tags=["agents"], response_model=list[dict])
    async def agents() -> list[dict[str, Any]]:
        """The agent catalogue: stages, contracts and tools."""
        return catalogue()  # type: ignore[return-value]

    @app.get("/api/schemas", tags=["contracts"])
    async def schemas() -> dict[str, Any]:
        """Published JSON Schema 2020-12 documents for every artifact."""
        from ..core.contracts import schema_dir

        out: dict[str, Any] = {}
        for path in sorted(schema_dir().glob("*.schema.json")):
            out[path.name.replace(".schema.json", "")] = json.loads(path.read_text())
        return out

    # -- runs --------------------------------------------------------------

    @app.post("/api/runs", tags=["runs"], response_model=RunSummary, status_code=202)
    async def create_run(request: RunRequest) -> RunSummary:
        """Start a build. Returns immediately; poll /api/runs/{id} or stream its events."""
        handle = registry.create(request.idea)
        await registry.start(handle, request, settings, resolved_llm)
        return RunSummary(run_id=handle.run_id, idea=handle.idea, status=handle.status)

    @app.get("/api/runs", tags=["runs"], response_model=list[RunSummary])
    async def list_runs() -> list[RunSummary]:
        return [_summarise(handle) for handle in registry.list()]

    @app.get("/api/runs/{run_id}", tags=["runs"])
    async def get_run(run_id: str) -> dict[str, Any]:
        handle = registry.get(run_id)
        payload: dict[str, Any] = {
            "run_id": handle.run_id,
            "idea": handle.idea,
            "status": handle.status,
            "error": handle.error,
        }
        if handle.outcome is not None:
            payload["report"] = handle.outcome.report.model_dump(mode="json")
        return payload

    @app.get("/api/runs/{run_id}/events", tags=["runs"])
    async def run_events(run_id: str) -> StreamingResponse:
        """Server-Sent event stream of pipeline progress."""
        handle = registry.get(run_id)

        async def frames():
            queue = handle.events.subscribe()
            try:
                while True:
                    event: Event = await queue.get()
                    yield f"data: {json.dumps(event.to_dict(), sort_keys=True)}\n\n"
                    if event.kind == "run" and event.message.startswith(("finished", "failed")):
                        break
            finally:
                handle.events.unsubscribe(queue)

        return StreamingResponse(frames(), media_type="text/event-stream")

    @app.get("/api/runs/{run_id}/report", tags=["runs"])
    async def run_report(run_id: str) -> dict[str, Any]:
        handle = registry.get(run_id)
        if handle.outcome is None:
            raise HTTPException(status_code=409, detail=f"run {run_id} has no report yet (status={handle.status})")
        return handle.outcome.report.model_dump(mode="json")

    # -- A2A endpoints per agent -------------------------------------------

    if enable_a2a:
        for stage, agent_cls in BY_STAGE.items():
            app.mount(
                f"/agents/{stage}",
                _agent_app(stage, agent_cls, settings, resolved_llm),
                name=f"a2a-{stage}",
            )

    @app.get("/api/a2a/cards", tags=["agents"])
    async def agent_cards(request: Request) -> dict[str, Any]:
        """Every agent card, as an A2A client would discover them."""
        base = str(request.base_url).rstrip("/")
        cards: dict[str, Any] = {}
        for stage, agent_cls in BY_STAGE.items():
            agent = agent_cls(resolved_llm)
            cards[stage] = agent.card(f"{base}/agents/{stage}/").to_wire()
        return cards

    return app


def _summarise(handle: RunHandle) -> RunSummary:
    report = getattr(getattr(handle, "outcome", None), "report", None)
    return RunSummary(
        run_id=handle.run_id,
        idea=handle.idea,
        status=handle.status,
        tests_passed=getattr(report, "tests_passed", 0),
        tests_failed=getattr(report, "tests_failed", 0),
        files=len(getattr(report, "files_written", []) or []),
        project_dir=getattr(report, "project_dir", ""),
    )


def _agent_app(stage: str, agent_cls: Any, settings: Settings, llm: LLMClient) -> FastAPI:
    """Wrap one stage agent as a standalone A2A server app."""
    agent = agent_cls(llm)
    base = f"http://{settings.default_host}:{settings.default_port}/agents/{stage}"

    async def handler(context: TaskContext, message: Message) -> None:
        inputs = _inputs_from_message(message)
        await context.working(f"{agent.display_name} starting")
        result = await agent.produce(inputs)
        await context.artifact(type(result).__name__, result.model_dump(mode="json"))
        await context.complete(f"produced {type(result).__name__}")

    return A2AServer(card=agent.card(base), handler=handler).app


def _inputs_from_message(message: Message) -> dict[str, Any]:
    """Rebuild agent inputs from A2A message parts.

    Convention: a DataPart whose metadata carries ``{"artifact": "Requirements"}``
    becomes a named artifact; plain text becomes the ``idea``.
    """
    inputs: dict[str, Any] = {}
    texts: list[str] = []
    for part in message.parts:
        if part.content_kind == "data" and isinstance(part.data, dict):
            name = (part.metadata or {}).get("artifact") if part.metadata else None
            if name:
                inputs[str(name)] = part.data
            else:
                inputs.update({k: v for k, v in part.data.items() if isinstance(k, str)})
        elif part.content_kind == "text":
            texts.append(part.text or "")
    if texts:
        inputs["idea"] = "\n".join(texts)
    return inputs


def serve(
    *,
    host: str | None = None,
    port: int | None = None,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    reload: bool = False,
) -> None:
    import uvicorn

    settings = settings or get_settings()
    app = create_app(settings=settings, llm=llm)
    uvicorn.run(app, host=host or settings.default_host, port=port or settings.default_port, reload=reload)
