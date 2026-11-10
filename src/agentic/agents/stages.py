"""The seven stage agents."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel

from ..core.events import Event
from ..core.spec import (
    Architecture,
    BuildResult,
    FileChange,
    IdeaBrief,
    Requirements,
    Review,
    TaskItem,
    TaskPlan,
    TestReport,
)
from ..mcp.toolbox import MCPToolbox
from .base import StageAgent, artifact_block


# ---------------------------------------------------------------------------
# 1. Idea scout
# ---------------------------------------------------------------------------


class IdeaScoutAgent(StageAgent):
    stage: ClassVar[str] = "scout"
    agent_id: ClassVar[str] = "idea-scout"
    display_name: ClassVar[str] = "Idea Scout"
    description: ClassVar[str] = (
        "Turns a vague idea into a sharp brief: the real problem, who it is for, what is explicitly "
        "out of scope, and how success will be measured."
    )
    tags: ClassVar[tuple[str, ...]] = ("discovery", "product", "scoping")
    output_model: ClassVar[type[BaseModel]] = IdeaBrief

    def system_prompt(self) -> str:
        return (
            "You are a pragmatic product engineer. Convert the idea into a brief that a team could "
            "start building from today.\n"
            "- Name the concrete problem, not the solution.\n"
            "- Be explicit about what is OUT of scope; scope creep kills small projects.\n"
            "- Success metrics must be objectively checkable (a command runs, a test passes), not vibes.\n"
            "- Keep it tight. Prefer 5 sharp items over 15 vague ones."
        )

    def user_prompt(self, inputs: dict[str, Any]) -> str:
        return f"IDEA:\n{inputs.get('idea', '').strip()}\n\nProduce the brief."


# ---------------------------------------------------------------------------
# 2. Requirements analyst
# ---------------------------------------------------------------------------


class AnalystAgent(StageAgent):
    stage: ClassVar[str] = "analyst"
    agent_id: ClassVar[str] = "requirements-analyst"
    display_name: ClassVar[str] = "Requirements Analyst"
    description: ClassVar[str] = (
        "Derives numbered functional and non-functional requirements with testable acceptance criteria."
    )
    tags: ClassVar[tuple[str, ...]] = ("requirements", "specification")
    output_model: ClassVar[type[BaseModel]] = Requirements
    requires: ClassVar[tuple[str, ...]] = ("IdeaBrief",)

    def system_prompt(self) -> str:
        return (
            "You are a requirements engineer.\n"
            "- Functional requirements get ids FR-001, FR-002, ... Non-functional get NFR-001, ...\n"
            "- Every requirement needs acceptance criteria that a test or a command can actually check. "
            "'It should be fast' is not acceptable; 'the test suite finishes in under 10 seconds' is.\n"
            "- Write each description as 'The system shall ...'.\n"
            "- project_name must be a lowercase snake_case identifier usable as a Python package name.\n"
            "- Do not invent features the brief did not ask for."
        )


# ---------------------------------------------------------------------------
# 3. Architect
# ---------------------------------------------------------------------------


class ArchitectAgent(StageAgent):
    stage: ClassVar[str] = "architect"
    agent_id: ClassVar[str] = "architect"
    display_name: ClassVar[str] = "Software Architect"
    description: ClassVar[str] = (
        "Chooses the stack and component layout, mapping every functional requirement to a module."
    )
    tags: ClassVar[tuple[str, ...]] = ("architecture", "design")
    output_model: ClassVar[type[BaseModel]] = Architecture
    requires: ClassVar[tuple[str, ...]] = ("Requirements",)

    def system_prompt(self) -> str:
        return (
            "You are a software architect who favours boring, dependable choices.\n"
            "- Pick the smallest stack that satisfies the requirements. Fewer dependencies win.\n"
            "- Every component lists the module file paths it owns, and the requirement ids it satisfies.\n"
            "- Component ids must be unique; depends_on may only reference existing component ids.\n"
            "- Record the trade-offs you made in 'decisions' so a reviewer can challenge them.\n"
            "- Module paths are relative to the project root, e.g. 'myapp/core.py'."
        )


# ---------------------------------------------------------------------------
# 4. Planner
# ---------------------------------------------------------------------------


class PlannerAgent(StageAgent):
    stage: ClassVar[str] = "planner"
    agent_id: ClassVar[str] = "planner"
    display_name: ClassVar[str] = "Task Planner"
    description: ClassVar[str] = (
        "Splits the architecture into a dependency-ordered task graph with explicit done-when criteria."
    )
    tags: ClassVar[tuple[str, ...]] = ("planning", "decomposition")
    output_model: ClassVar[type[BaseModel]] = TaskPlan
    requires: ClassVar[tuple[str, ...]] = ("Architecture", "Requirements")

    def system_prompt(self) -> str:
        return (
            "You are a technical planner.\n"
            "- Produce 3 to 12 tasks. Each is small enough to implement and verify in one sitting.\n"
            "- depends_on must form a DAG (no cycles) and may only reference other task ids in this plan.\n"
            "- Order matters: foundational modules come before things that import them.\n"
            "- Every task lists the files it creates and the requirement ids it satisfies.\n"
            "- 'done_when' items must be objectively verifiable (a file exists, a test passes).\n"
            "- Task ids are slugs like 'task-1', 'task-core', 'task-cli'."
        )

    def user_prompt(self, inputs: dict[str, Any]) -> str:
        reqs: Requirements = inputs["Requirements"]
        arch: Architecture = inputs["Architecture"]
        paths = "\n".join(f"  - {p}" for p in arch.all_paths())
        return (
            f"Requirements summary: {reqs.summary}\n"
            f"Functional requirements: {', '.join(r.id for r in reqs.functional())}\n"
            f"Architecture overview: {arch.overview}\n"
            f"Files the architecture declares:\n{paths}\n\n"
            f"Full artifacts:\n\n{artifact_block(inputs)}"
        )


# ---------------------------------------------------------------------------
# 5. Builder (writes to disk through MCP)
# ---------------------------------------------------------------------------


class BuilderAgent(StageAgent):
    stage: ClassVar[str] = "builder"
    agent_id: ClassVar[str] = "builder"
    display_name: ClassVar[str] = "Implementer"
    description: ClassVar[str] = (
        "Implements one task at a time, writing complete files to the workspace through MCP tools."
    )
    tags: ClassVar[tuple[str, ...]] = ("implementation", "coding")
    output_model: ClassVar[type[BaseModel]] = BuildResult
    requires: ClassVar[tuple[str, ...]] = ("TaskItem", "Architecture", "Requirements")
    uses_tools: ClassVar[tuple[str, ...]] = ("workspace",)

    def system_prompt(self) -> str:
        return (
            "You are a senior implementer.\n"
            "- Return COMPLETE file contents. Never use placeholders, '...' or TODO stubs.\n"
            "- Paths are relative to the project root and must match the architecture's module layout.\n"
            "- Code must import cleanly and run on the declared stack with its declared dependencies.\n"
            "- Match the existing style of any file you modify.\n"
            "- If you deviate from the architecture, say so in 'deviations' — do not silently redesign."
        )

    def user_prompt(self, inputs: dict[str, Any]) -> str:
        task: TaskItem = inputs["TaskItem"]
        existing = inputs.get("existing_files")
        parts = [
            f"TASK: {task.title}\n{task.description}\n",
            f"Files to produce: {', '.join(task.target_files)}",
            f"Satisfies: {', '.join(task.requirement_ids)}",
            f"Done when: {'; '.join(task.done_when)}",
        ]
        if existing:
            parts.append(f"\nFiles already on disk:\n{existing}")
        if inputs.get("repair"):
            parts.append(f"\nREPAIR REQUESTED — previous attempt failed:\n{inputs['repair']}")
        parts.append(f"\nContext artifacts:\n\n{artifact_block({k: v for k, v in inputs.items() if k in ('Architecture', 'Requirements', 'TaskItem')})}")
        return "\n".join(parts)

    async def produce(self, inputs: dict[str, Any], **kwargs: Any) -> BuildResult:  # type: ignore[override]
        toolbox: MCPToolbox | None = kwargs.pop("toolbox", None)
        result: BuildResult = await super().produce(inputs, **kwargs)  # type: ignore[assignment]
        if toolbox is not None and toolbox.servers:
            written = await write_changes(toolbox, result.files)
            result = result.model_copy(update={"files": written})
        return result


async def write_changes(toolbox: MCPToolbox, files: list[FileChange]) -> list[FileChange]:
    """Apply file changes through the workspace MCP server."""
    applied: list[FileChange] = []
    for change in files:
        if change.action.value == "delete":
            response = await toolbox.call("workspace", "delete_file", {"path": change.path})
        else:
            response = await toolbox.call(
                "workspace", "write_file", {"path": change.path, "content": change.content}
            )
        if not response.get("ok"):
            raise RuntimeError(f"workspace rejected {change.path}: {response.get('error')}")
        applied.append(change)
    return applied


# ---------------------------------------------------------------------------
# 6. Verifier (deterministic — it runs the real test suite)
# ---------------------------------------------------------------------------

_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERROR_RE = re.compile(r"(\d+)\s+error")
_SKIPPED_RE = re.compile(r"(\d+)\s+skipped")
_DURATION_RE = re.compile(r"in\s+([\d.]+)s")
_FAIL_LINE_RE = re.compile(r"^(?:FAILED|ERROR)\s+\S+", re.MULTILINE)


class VerifierAgent(StageAgent):
    stage: ClassVar[str] = "verifier"
    agent_id: ClassVar[str] = "verifier"
    display_name: ClassVar[str] = "Verifier"
    description: ClassVar[str] = (
        "Runs the project's real test suite through the sandbox MCP server and reports what actually "
        "happened. Never asks a model what it thinks the tests did."
    )
    tags: ClassVar[tuple[str, ...]] = ("testing", "verification")
    output_model: ClassVar[type[BaseModel]] = TestReport
    uses_tools: ClassVar[tuple[str, ...]] = ("sandbox",)

    def system_prompt(self) -> str:
        return "This stage executes commands; it does not generate text."

    async def produce(self, inputs: dict[str, Any], **kwargs: Any) -> TestReport:  # type: ignore[override]
        toolbox: MCPToolbox | None = kwargs.pop("toolbox", None)
        task_id = str(inputs.get("task_id", "all"))
        framework = str(inputs.get("framework", "pytest"))
        if toolbox is None or not toolbox.servers:
            return TestReport(
                task_id=task_id,
                command="(no sandbox)",
                success=False,
                exit_code=1,
                environment_ok=False,
                failures=["no sandbox MCP server available; cannot verify"],
            )
        syntax = await toolbox.call("sandbox", "check_python_syntax", {})
        if not syntax.get("ok", True):
            problems = syntax.get("problems", []) or []
            failures = [f"{p.get('path')}:{p.get('line') or '?'}: {p.get('message')}" for p in problems]
            report = TestReport(
                task_id=task_id,
                command="check_python_syntax",
                success=False,
                exit_code=1,
                errors=len(problems),
                failures=failures,
                raw_output="\n".join(failures),
            )
        else:
            response = await toolbox.call("sandbox", "run_tests", {"framework": framework})
            report = parse_test_output(task_id, response)
        if self.events:
            self.events.emit(
                Event(
                    kind="tests",
                    stage=self.stage,
                    agent=self.agent_id,
                    message=(
                        f"{report.passed} passed, {report.failed} failed, {report.errors} errors"
                        if report.environment_ok
                        else "test environment unavailable"
                    ),
                    data={"success": report.success, "exit_code": report.exit_code},
                )
            )
        return report


def parse_test_output(task_id: str, response: dict[str, Any]) -> TestReport:
    """Turn sandbox output into a TestReport."""
    combined = f"{response.get('stdout', '')}\n{response.get('stderr', '')}"
    if not response.get("ok") and response.get("error"):
        return TestReport(
            task_id=task_id,
            command=response.get("command", "run_tests"),
            success=False,
            exit_code=1,
            environment_ok=False,
            failures=[str(response["error"])],
            raw_output=str(response.get("error")),
        )

    def grab(pattern: re.Pattern[str]) -> int:
        match = pattern.search(combined)
        return int(match.group(1)) if match else 0

    duration_match = _DURATION_RE.search(combined)
    exit_code = int(response.get("exit_code", 1) or 0)
    passed, failed, errors, skipped = (
        grab(_PASSED_RE),
        grab(_FAILED_RE),
        grab(_ERROR_RE),
        grab(_SKIPPED_RE),
    )
    no_tests = "no tests ran" in combined or "collected 0 items" in combined
    success = exit_code == 0 and not no_tests and errors == 0 and failed == 0
    failures = [line.strip() for line in _FAIL_LINE_RE.findall(combined)][:20]
    if no_tests:
        failures.append("the test suite collected zero tests — nothing was actually verified")
        success = False
    return TestReport(
        task_id=task_id,
        command=str(response.get("command", "pytest -q")),
        success=success,
        exit_code=exit_code,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_s=float(duration_match.group(1)) if duration_match else 0.0,
        environment_ok=True,
        failures=failures,
        raw_output=combined[-8000:],
    )


# ---------------------------------------------------------------------------
# 7. Reviewer
# ---------------------------------------------------------------------------


class ReviewerAgent(StageAgent):
    stage: ClassVar[str] = "reviewer"
    agent_id: ClassVar[str] = "reviewer"
    display_name: ClassVar[str] = "Code Reviewer"
    description: ClassVar[str] = (
        "Reviews the produced code against the requirements and the test evidence, and either "
        "approves or requests specific changes."
    )
    tags: ClassVar[tuple[str, ...]] = ("review", "quality")
    output_model: ClassVar[type[BaseModel]] = Review
    requires: ClassVar[tuple[str, ...]] = ("Requirements", "TestReport")

    def system_prompt(self) -> str:
        return (
            "You are a rigorous but fair code reviewer.\n"
            "- Judge the code against the requirements and the test evidence, not your taste.\n"
            "- 'blocker' means do not ship. 'major' means fix before merge. 'minor'/'info' are advisory.\n"
            "- Every finding needs a concrete suggested_fix, or it is not worth reporting.\n"
            "- If the suite is green and requirements are covered, approve. Do not invent problems.\n"
            "- Finding ids are slugs like 'f-1', 'f-2'."
        )

    def user_prompt(self, inputs: dict[str, Any]) -> str:
        report: TestReport = inputs["TestReport"]
        files = inputs.get("files") or []
        listing = "\n".join(f"  - {f}" for f in files[:60])
        return (
            f"Test evidence: {report.passed} passed, {report.failed} failed, {report.errors} errors "
            f"(exit {report.exit_code})\nCommand: {report.command}\n"
            f"Files produced:\n{listing}\n\n"
            f"{artifact_block(inputs)}"
        )
