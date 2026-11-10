"""Orchestrator: drives the pipeline from idea to a verified, reviewed project.

The loop is the point. A stage is not "done" because a model said so — it is
done when the sandbox reports a green suite and the reviewer approves. Failures
feed straight back into the builder as concrete repair context.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..agents.base import StageAgent
from ..agents.registry import build_all_agents
from ..agents.stages import write_changes
from ..config import Settings, get_settings
from ..core.artifacts import ArtifactStore
from ..core.events import Event, EventBus
from ..core.spec import (
    Architecture,
    BuildResult,
    FileChange,
    IdeaBrief,
    Requirements,
    Review,
    RunReport,
    StageRecord,
    StageStatus,
    TaskItem,
    TaskPlan,
    TestReport,
    Verdict,
    slugify,
)
from ..errors import AgenticError
from ..llm.base import LLMClient
from ..llm.mock import MockLLM
from ..llm.openai_compat import OpenAICompatLLM
from ..mcp.toolbox import MCPToolbox, ServerSpec
from .graph import RunState

log = logging.getLogger(__name__)


def default_llm(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    if settings.llm_mode == "mock":
        return MockLLM()
    return OpenAICompatLLM(
        settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
    )


@dataclass
class RunOutcome:
    report: RunReport
    artifacts: dict[str, Any] = field(default_factory=dict)
    project_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return self.report.status == "completed"


class Orchestrator:
    """Runs the full pipeline for one idea."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        events: EventBus | None = None,
        run_id: str | None = None,
        workspace: Path | None = None,
        use_mcp: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.events = events or EventBus()
        self.llm = llm or default_llm(self.settings)
        self.run_id = run_id or f"run-{uuid4().hex[:10]}"
        self.use_mcp = self.settings.enable_mcp if use_mcp is None else use_mcp
        base = Path(workspace) if workspace else self.settings.runs_dir
        self.store = ArtifactStore(base / self.run_id, self.run_id)
        self.agents: dict[str, StageAgent] = build_all_agents(self.llm, self.events)
        self.state = RunState()

    # -- public ----------------------------------------------------------

    async def build(self, idea: str, *, max_fix_rounds: int | None = None) -> RunOutcome:
        idea = (idea or "").strip()
        if not idea:
            raise AgenticError("an idea is required")
        rounds = self.settings.max_fix_rounds if max_fix_rounds is None else max_fix_rounds
        started = time.perf_counter()
        self._emit("run", "", "started", {"idea": idea[:200], "llm": self.llm.name})

        records: list[StageRecord] = []
        artifacts: dict[str, Any] = {}
        try:
            await self._run_stage("scout", {"idea": idea}, records, artifacts)
            await self._run_stage("analyst", {}, records, artifacts)
            await self._run_stage("architect", {}, records, artifacts)
            await self._run_stage("planner", {}, records, artifacts)

            plan: TaskPlan = self.state.require("TaskPlan")["TaskPlan"]  # type: ignore[assignment]
            async with MCPToolbox(self._specs(), enabled=self.use_mcp) as toolbox:
                await self._ensure_scaffold(toolbox)
                await self._build_tasks(plan, toolbox, records, artifacts)
                report, review, fix_rounds = await self._verify_review_loop(
                    toolbox, records, artifacts, rounds
                )

            await self._finalise_project(artifacts)
            run_report = self._summarise(idea, records, artifacts, report, review, fix_rounds, started)
            self.store.put_model("RunReport", run_report)
            self._emit("run", "", f"finished: {run_report.status}", {"status": run_report.status})
            return RunOutcome(
                report=run_report,
                artifacts=artifacts,
                project_dir=self.store.project_dir,
            )
        except AgenticError as exc:
            records.append(StageRecord(stage="run", agent="orchestrator", status=StageStatus.FAILED, detail=str(exc)))
            failed = RunReport(
                run_id=self.run_id,
                idea=idea,
                status="failed",
                stages=records,
                project_dir=str(self.store.project_dir),
                summary=f"run aborted: {exc}",
            )
            self.store.put_model("RunReport", failed)
            self._emit("run", "", f"failed: {exc}", {"status": "failed"})
            return RunOutcome(report=failed, artifacts=artifacts, project_dir=self.store.project_dir)

    # -- stages ----------------------------------------------------------

    async def _run_stage(
        self,
        stage: str,
        extra_inputs: dict[str, Any],
        records: list[StageRecord],
        artifacts: dict[str, Any],
    ) -> Any:
        agent = self.agents[stage]
        stage_def_inputs = _stage_inputs(stage)
        inputs = dict(extra_inputs)
        if stage_def_inputs:
            inputs.update(self.state.require(*stage_def_inputs))

        self._emit(stage, agent.agent_id, "start")
        started = time.perf_counter()
        try:
            result = await agent.produce(inputs)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised as a stage failure
            elapsed = time.perf_counter() - started
            records.append(
                StageRecord(stage=stage, agent=agent.agent_id, status=StageStatus.FAILED, detail=str(exc)[:500])
            )
            self._emit(stage, agent.agent_id, f"failed: {exc}")
            raise AgenticError(f"stage {stage!r} failed: {exc}") from exc

        elapsed = time.perf_counter() - started
        name = type(result).__name__
        stored = self.store.put_model(name, result)
        self.state.put(name, result)
        artifacts[name] = result
        records.append(
            StageRecord(
                stage=stage,
                agent=agent.agent_id,
                status=StageStatus.COMPLETED,
                detail=name,
                artifact_ref=stored.uri,
                duration_s=round(elapsed, 3),
            )
        )
        self._emit(stage, agent.agent_id, f"produced {name}", {"uri": stored.uri})
        return result

    # -- build loop ------------------------------------------------------

    async def _build_tasks(
        self, plan: TaskPlan, toolbox: MCPToolbox, records: list[StageRecord], artifacts: dict[str, Any]
    ) -> None:
        builder = self.agents["builder"]
        order = plan.build_order()
        self._emit("build", builder.agent_id, f"{len(order)} tasks in order: {' -> '.join(order)}")
        for task_id in order:
            task = next(t for t in plan.tasks if t.id == task_id)
            self._emit("build", builder.agent_id, f"task {task.id}: {task.title}")
            started = time.perf_counter()
            inputs = {
                "TaskItem": task,
                "Architecture": self.state.require("Architecture")["Architecture"],
                "Requirements": self.state.require("Requirements")["Requirements"],
                "existing_files": await _existing_files(toolbox),
            }
            try:
                result: BuildResult = await builder.produce(inputs, toolbox=toolbox)  # type: ignore[assignment]
            except Exception as exc:  # noqa: BLE001
                records.append(
                    StageRecord(
                        stage="build",
                        agent=builder.agent_id,
                        status=StageStatus.FAILED,
                        detail=f"{task.id}: {exc}"[:500],
                    )
                )
                self._emit("build", builder.agent_id, f"task {task.id} failed: {exc}")
                raise AgenticError(f"build task {task.id} failed: {exc}") from exc

            stored = self.store.put_json("BuildResult", result.model_dump(mode="json"))
            artifacts.setdefault("BuildResults", []).append(result)
            records.append(
                StageRecord(
                    stage="build",
                    agent=builder.agent_id,
                    status=StageStatus.COMPLETED,
                    detail=f"{task.id}: {len(result.files)} file(s)",
                    artifact_ref=stored.uri,
                    duration_s=round(time.perf_counter() - started, 3),
                )
            )
            self._emit(
                "build",
                builder.agent_id,
                f"task {task.id} wrote {len(result.files)} file(s)",
                {"files": [f.path for f in result.files]},
            )

    async def _verify_review_loop(
        self, toolbox: MCPToolbox, records: list[StageRecord], artifacts: dict[str, Any], rounds: int
    ) -> tuple[TestReport, Review, int]:
        verifier = self.agents["verifier"]
        reviewer = self.agents["reviewer"]
        builder = self.agents["builder"]

        report = TestReport(task_id="all", command="(not run)", success=False)
        review = Review(verdict=Verdict.REQUEST_CHANGES, summary="not reviewed yet")

        for round_index in range(rounds + 1):
            self._emit("verify", verifier.agent_id, f"verification pass {round_index + 1}")
            report = await verifier.produce({"task_id": "all", "framework": "pytest"}, toolbox=toolbox)  # type: ignore[assignment]
            self.store.put_model("TestReport", report)
            artifacts["TestReport"] = report
            records.append(
                StageRecord(
                    stage="verify",
                    agent=verifier.agent_id,
                    status=StageStatus.COMPLETED if report.success else StageStatus.FAILED,
                    detail=f"{report.passed} passed / {report.failed} failed / {report.errors} errors",
                )
            )

            review = await reviewer.produce(  # type: ignore[assignment]
                {
                    "Requirements": self.state.require("Requirements")["Requirements"],
                    "TestReport": report,
                    "files": sorted({f.path for r in artifacts.get("BuildResults", []) for f in r.files}),
                }
            )
            self.store.put_model("Review", review)
            artifacts["Review"] = review
            records.append(
                StageRecord(
                    stage="review",
                    agent=reviewer.agent_id,
                    status=StageStatus.COMPLETED,
                    detail=f"{review.verdict.value}: {len(review.findings)} finding(s)",
                )
            )

            if report.success and review.verdict is Verdict.APPROVE and not review.blocking:
                self._emit("review", reviewer.agent_id, "approved — suite green and no blocking findings")
                return report, review, round_index

            if round_index >= rounds:
                self._emit("review", reviewer.agent_id, "fix budget exhausted")
                return report, review, round_index

            self._emit(
                "fix",
                builder.agent_id,
                f"round {round_index + 1}: repairing {report.failed} failure(s), {len(review.blocking)} blocking finding(s)",
            )
            await self._repair(toolbox, report, review, round_index, records)

        return report, review, rounds

    async def _repair(
        self, toolbox: MCPToolbox, report: TestReport, review: Review, round_index: int, records: list[StageRecord]
    ) -> None:
        builder = self.agents["builder"]
        evidence = _repair_evidence(report, review)
        targets = await _project_source_files(toolbox)
        task = TaskItem(
            id=f"fix-{round_index + 1}",
            title=f"Repair failing tests and blocking review findings (round {round_index + 1})",
            description=(
                "The verification suite is not green and/or the reviewer raised blocking findings. "
                "Fix the implementation. Do not weaken or delete tests to make them pass."
            ),
            component_ids=["core", "cli"],
            target_files=targets,
            depends_on=[],
            requirement_ids=[r.id for r in self.state.require("Requirements")["Requirements"].functional()],  # type: ignore[union-attr]
            done_when=["pytest exits 0", "no blocking review findings remain"],
        )
        inputs = {
            "TaskItem": task,
            "Architecture": self.state.require("Architecture")["Architecture"],
            "Requirements": self.state.require("Requirements")["Requirements"],
            "repair": evidence,
            "existing_files": await _existing_files(toolbox),
        }
        result: BuildResult = await builder.produce(inputs, toolbox=toolbox)  # type: ignore[assignment]
        self.store.put_model("BuildResult", result)
        records.append(
            StageRecord(
                stage="fix",
                agent=builder.agent_id,
                status=StageStatus.COMPLETED,
                detail=f"round {round_index + 1}: rewrote {len(result.files)} file(s)",
            )
        )

    # -- helpers ---------------------------------------------------------

    def _specs(self) -> list[ServerSpec]:
        if not self.use_mcp:
            return []
        project = self.store.project_dir
        return [
            ServerSpec.workspace(project),
            ServerSpec.sandbox(project, timeout=min(300.0, self.settings.timeout)),
        ]

    async def _ensure_scaffold(self, toolbox: MCPToolbox) -> None:
        """Guarantee a runnable test harness even if the model forgets one."""
        if not toolbox.servers:
            return
        listing = await toolbox.call("workspace", "list_files", {"pattern": "pyproject.toml"})
        if listing.get("files"):
            return
        name = "app"
        try:
            name = self.state.require("Requirements")["Requirements"].project_name  # type: ignore[union-attr]
        except KeyError:
            pass
        await toolbox.call(
            "workspace",
            "write_file",
            {
                "path": "pyproject.toml",
                "content": (
                    "[project]\n"
                    f'name = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
                    "dependencies = []\n\n"
                    "[dependency-groups]\ndev = [\"pytest>=8.0\"]\n\n"
                    "[tool.pytest.ini_options]\n"
                    'pythonpath = ["."]\ntestpaths = ["tests"]\n'
                ),
            },
        )
        self._emit("build", "orchestrator", "added missing pyproject.toml scaffold")

    async def _finalise_project(self, artifacts: dict[str, Any]) -> None:
        """Write AGENTS.md so any agent opening the project understands it."""
        reqs: Requirements | None = artifacts.get("Requirements")
        arch: Architecture | None = artifacts.get("Architecture")
        plan: TaskPlan | None = artifacts.get("TaskPlan")
        lines = [
            "# AGENTS.md",
            "",
            "Instructions for AI agents working in this repository.",
            "",
            "## What this is",
            "",
            (reqs.summary if reqs else "A generated project."),
            "",
            "## Layout",
            "",
        ]
        if arch:
            lines += [f"- `{m.path}` — {m.purpose}" for c in arch.components for m in c.modules]
        else:
            lines.append("- see README.md")
        lines += [
            "",
            "## Rules",
            "",
            "- Run `pytest -q` before declaring anything done.",
            "- Never delete or weaken a test to make the suite pass.",
            "- Keep core functions pure; put side effects at the edges.",
            "- All paths in tool calls are relative to the repository root.",
            "",
            "## Commands",
            "",
            "```bash",
            "pytest -q",
            "```",
            "",
        ]
        if plan:
            lines += ["## Build order", "", *[f"- `{t.id}` {t.title}" for t in plan.tasks], ""]
        (self.store.project_dir / "AGENTS.md").write_text("\n".join(lines), encoding="utf-8")

    def _summarise(
        self,
        idea: str,
        records: list[StageRecord],
        artifacts: dict[str, Any],
        report: TestReport,
        review: Review,
        fix_rounds: int,
        started: float,
    ) -> RunReport:
        reqs: Requirements | None = artifacts.get("Requirements")
        arch: Architecture | None = artifacts.get("Architecture")
        files = sorted({f.path for r in artifacts.get("BuildResults", []) for f in r.files})
        total = len(reqs.functional()) if reqs else 0
        # Coverage = requirement ids named by the architecture components.
        covered_ids: set[str] = set()
        if arch:
            for component in arch.components:
                covered_ids.update(component.requirement_ids)
        status = "completed" if (report.success and review.verdict is Verdict.APPROVE) else "failed"
        entry = arch.entry_points[0].invocation if arch and arch.entry_points else "pytest -q"
        return RunReport(
            run_id=self.run_id,
            idea=idea,
            status=status,
            project_dir=str(self.store.project_dir),
            stages=records,
            requirements_covered=sorted(covered_ids),
            requirements_total=total,
            fix_rounds=fix_rounds,
            tests_passed=report.passed,
            tests_failed=report.failed,
            files_written=files,
            how_to_run=["uv sync", "uv run pytest -q", entry],
            summary=(
                f"{report.passed} test(s) passing, {report.failed} failing; review {review.verdict.value}; "
                f"{len(files)} file(s) written in {time.perf_counter() - started:.1f}s."
            ),
        )

    def _emit(self, stage: str, agent: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.events.emit(Event(kind="stage", stage=stage, agent=agent, message=message, data=data or {}))


def _stage_inputs(stage: str) -> tuple[str, ...]:
    from .graph import BY_NAME

    definition = BY_NAME.get(stage)
    return tuple(i for i in (definition.inputs if definition else ()) if i != "idea")


def _repair_evidence(report: TestReport, review: Review) -> str:
    parts = [
        f"Test command: {report.command} (exit {report.exit_code})",
        f"Result: {report.passed} passed, {report.failed} failed, {report.errors} errors",
    ]
    if report.failures:
        parts.append("Failures:\n" + "\n".join(f"  - {f}" for f in report.failures[:15]))
    if review.blocking:
        parts.append(
            "Blocking review findings:\n"
            + "\n".join(
                f"  - [{f.severity.value}] {f.location or f.category}: {f.description}"
                + (f" -> {f.suggested_fix}" if f.suggested_fix else "")
                for f in review.blocking[:10]
            )
        )
    tail = report.raw_output[-3000:] if report.raw_output else ""
    if tail:
        parts.append("Captured output (tail):\n" + tail)
    return "\n\n".join(parts)


async def _project_source_files(toolbox: MCPToolbox) -> list[str]:
    """Files a repair pass may rewrite, read from the live workspace."""
    files: list[str] = []
    if toolbox.servers:
        listing = await toolbox.call("workspace", "list_files", {"pattern": "**/*.py"})
        files = [
            f["path"]
            for f in listing.get("files", [])
            if f["path"].endswith(".py") and not f["path"].startswith("tests/")
        ]
    return files or ["app/core.py"]


async def _existing_files(toolbox: MCPToolbox) -> str:
    if not toolbox.servers:
        return "(workspace not available)"
    listing = await toolbox.call("workspace", "list_files", {"pattern": "**/*"})
    files = listing.get("files", [])
    if not files:
        return "(empty workspace)"
    return "\n".join(f"- {f['path']} ({f['size']} bytes)" for f in files[:80])
