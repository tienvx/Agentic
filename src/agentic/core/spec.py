"""Domain models for every artifact produced by the pipeline.

These Pydantic models are the *source of truth*: JSON Schema 2020-12 files are
generated from them into ``schemas/`` and are what remote agents validate
against. Any agent — in any language — can consume them.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Conventions
# ---------------------------------------------------------------------------

Slug = Annotated[str, Field(min_length=1, max_length=64)]
IdStr = Annotated[str, Field(min_length=1, max_length=128)]


class Strict(BaseModel):
    """Base model: unknown keys are rejected so contract drift is loud."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class Priority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class RequirementKind(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non-functional"


class Severity(str, Enum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Verdict(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class FileAction(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Stage 1 — idea brief
# ---------------------------------------------------------------------------


class IdeaBrief(Strict):
    """Stage 1 output: a sharpened, testable reading of the raw idea."""

    schema_version: Literal["1"] = "1"
    title: Annotated[str, Field(min_length=3, max_length=120)]
    one_liner: Annotated[str, Field(min_length=10, max_length=240)]
    problem: Annotated[str, Field(min_length=20)]
    users: Annotated[list[str], Field(min_length=1, max_length=12)]
    value: Annotated[str, Field(min_length=10)]
    constraints: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    success_metrics: Annotated[list[str], Field(min_length=1, max_length=8)]

    @property
    def slug(self) -> str:
        return slugify(self.title)


# ---------------------------------------------------------------------------
# Stage 2 — requirements
# ---------------------------------------------------------------------------

_REQ_ID = re.compile(r"^(FR|NFR)-[0-9]{3}$")


class Requirement(Strict):
    id: str
    kind: RequirementKind
    title: Annotated[str, Field(min_length=3, max_length=160)]
    description: Annotated[str, Field(min_length=15)]
    rationale: str = ""
    acceptance_criteria: Annotated[list[str], Field(min_length=1, max_length=10)]
    priority: Priority = Priority.MUST

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _REQ_ID.match(v):
            raise ValueError(f"requirement id {v!r} must match FR-NNN or NFR-NNN")
        return v

    @field_validator("acceptance_criteria")
    @classmethod
    def _check_criteria(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) < 8:
                raise ValueError("acceptance criteria must be specific (>= 8 chars)")
        return v


class Requirements(Strict):
    schema_version: Literal["1"] = "1"
    project_name: Slug
    summary: Annotated[str, Field(min_length=20)]
    requirements: Annotated[list[Requirement], Field(min_length=1, max_length=60)]
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _unique_ids(cls, v: list[Requirement]) -> list[Requirement]:
        seen: set[str] = set()
        for req in v:
            if req.id in seen:
                raise ValueError(f"duplicate requirement id {req.id}")
            seen.add(req.id)
        if not any(r.kind is RequirementKind.FUNCTIONAL for r in v):
            raise ValueError("at least one functional requirement (FR-*) is required")
        return v

    def functional(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind is RequirementKind.FUNCTIONAL]

    def by_id(self, req_id: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == req_id), None)


# ---------------------------------------------------------------------------
# Stage 3 — architecture
# ---------------------------------------------------------------------------


class Stack(Strict):
    language: Annotated[str, Field(min_length=1)] = "python"
    runtime: str = "cpython>=3.11"
    framework: str = "none"
    build_tool: str = "hatch"
    test_framework: str = "pytest"
    package_manager: str = "uv"
    dependencies: list[str] = Field(default_factory=list)


class ModuleSpec(Strict):
    path: Annotated[str, Field(min_length=1)]
    purpose: Annotated[str, Field(min_length=5)]
    symbols: list[str] = Field(default_factory=list)


class Component(Strict):
    id: Slug
    name: Annotated[str, Field(min_length=2)]
    responsibility: Annotated[str, Field(min_length=10)]
    modules: Annotated[list[ModuleSpec], Field(min_length=1)]
    depends_on: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class EntryPoint(Strict):
    name: str
    kind: Literal["cli", "http", "library", "job"] = "cli"
    invocation: Annotated[str, Field(min_length=1)]
    description: str = ""


class Architecture(Strict):
    schema_version: Literal["1"] = "1"
    stack: Stack = Field(default_factory=Stack)
    overview: Annotated[str, Field(min_length=20)]
    components: Annotated[list[Component], Field(min_length=1, max_length=40)]
    entry_points: Annotated[list[EntryPoint], Field(min_length=1)]
    data_flow: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def _unique_component_ids(cls, v: list[Component]) -> list[Component]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate component id in architecture")
        known = set(ids)
        for comp in v:
            for dep in comp.depends_on:
                if dep not in known:
                    raise ValueError(f"component {comp.id!r} depends on unknown {dep!r}")
                if dep == comp.id:
                    raise ValueError(f"component {comp.id!r} depends on itself")
        return v

    def all_paths(self) -> list[str]:
        return sorted({m.path for c in self.components for m in c.modules})


# ---------------------------------------------------------------------------
# Stage 4 — plan
# ---------------------------------------------------------------------------


class TaskItem(Strict):
    id: Slug
    title: Annotated[str, Field(min_length=3, max_length=160)]
    description: Annotated[str, Field(min_length=15)]
    component_ids: Annotated[list[str], Field(min_length=1)]
    target_files: Annotated[list[str], Field(min_length=1, max_length=40)]
    depends_on: list[str] = Field(default_factory=list)
    requirement_ids: Annotated[list[str], Field(min_length=1)]
    done_when: Annotated[list[str], Field(min_length=1, max_length=10)]

    @field_validator("target_files")
    @classmethod
    def _no_absolute(cls, v: list[str]) -> list[str]:
        for path in v:
            if path.startswith("/") or ".." in Path_parts(path):
                raise ValueError(f"target file {path!r} must be a safe relative path")
        return v


def Path_parts(path: str) -> list[str]:  # noqa: N802 - tiny helper, kept readable
    return path.replace("\\", "/").split("/")


class TaskPlan(Strict):
    schema_version: Literal["1"] = "1"
    goal: Annotated[str, Field(min_length=10)]
    tasks: Annotated[list[TaskItem], Field(min_length=1, max_length=60)]

    @field_validator("tasks")
    @classmethod
    def _acyclic(cls, v: list[TaskItem]) -> list[TaskItem]:
        ids = [t.id for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task id in plan")
        known = set(ids)
        for task in v:
            for dep in task.depends_on:
                if dep not in known:
                    raise ValueError(f"task {task.id!r} depends on unknown task {dep!r}")
        # Kahn's algorithm — reject cycles so the builder cannot deadlock.
        indeg = {t.id: 0 for t in v}
        children: dict[str, list[str]] = {t.id: [] for t in v}
        for task in v:
            for dep in task.depends_on:
                indeg[task.id] += 1
                children[dep].append(task.id)
        queue = [tid for tid, d in indeg.items() if d == 0]
        seen = 0
        while queue:
            node = queue.pop()
            seen += 1
            for child in children[node]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    queue.append(child)
        if seen != len(v):
            raise ValueError("task dependency graph contains a cycle")
        return v

    def build_order(self) -> list[str]:
        """Deterministic topological order (ties broken by task id)."""
        indeg = {t.id: 0 for t in self.tasks}
        children: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                indeg[task.id] += 1
                children[dep].append(task.id)
        ready = sorted(tid for tid, d in indeg.items() if d == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for child in children[node]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    ready.append(child)
            ready.sort()
        return order


# ---------------------------------------------------------------------------
# Stage 5 — build
# ---------------------------------------------------------------------------


class FileChange(Strict):
    path: Annotated[str, Field(min_length=1)]
    action: FileAction = FileAction.CREATE
    content: str = ""

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        clean = v.replace("\\", "/").strip("/")
        parts = clean.split("/")
        if not clean or any(p in ("", ".", "..") for p in parts):
            raise ValueError(f"unsafe path {v!r}")
        if clean.startswith(("/", "~")):
            raise ValueError(f"path must be relative: {v!r}")
        return clean

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:12]


class BuildResult(Strict):
    schema_version: Literal["1"] = "1"
    task_id: Slug
    status: Literal["ok", "partial", "failed"] = "ok"
    files: Annotated[list[FileChange], Field(min_length=1)]
    notes: str = ""
    deviations: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 6 — verification
# ---------------------------------------------------------------------------


class TestReport(Strict):
    """Verification evidence. ``__test__`` keeps pytest from collecting this model."""

    __test__ = False

    schema_version: Literal["1"] = "1"
    task_id: Slug = Field(default="all")
    command: Annotated[str, Field(min_length=1)] = "pytest -q"
    success: bool = False
    exit_code: int = 1
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    environment_ok: bool = True
    failures: list[str] = Field(default_factory=list)
    raw_output: str = ""


# ---------------------------------------------------------------------------
# Stage 7 — review
# ---------------------------------------------------------------------------


class Finding(Strict):
    id: Slug
    severity: Severity
    category: Annotated[str, Field(min_length=2)] = "correctness"
    location: str = ""
    description: Annotated[str, Field(min_length=10)]
    suggested_fix: str = ""
    requirement_id: str = ""


class Review(Strict):
    schema_version: Literal["1"] = "1"
    verdict: Verdict = Verdict.APPROVE
    summary: Annotated[str, Field(min_length=10)]
    findings: list[Finding] = Field(default_factory=list)

    @field_validator("verdict")
    @classmethod
    def _default_verdict(cls, v: Verdict, info) -> Verdict:  # type: ignore[no-untyped-def]
        return v

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in (Severity.BLOCKER, Severity.MAJOR)]


# ---------------------------------------------------------------------------
# Run report
# ---------------------------------------------------------------------------


class StageRecord(Strict):
    stage: Slug
    agent: str
    status: StageStatus
    attempts: int = 1
    detail: str = ""
    artifact_ref: str = ""
    duration_s: float = 0.0


class RunReport(Strict):
    schema_version: Literal["1"] = "1"
    run_id: str
    idea: str
    status: Literal["completed", "failed"] = "failed"
    project_dir: str = ""
    stages: list[StageRecord] = Field(default_factory=list)
    requirements_covered: list[str] = Field(default_factory=list)
    requirements_total: int = 0
    fix_rounds: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    files_written: list[str] = Field(default_factory=list)
    how_to_run: list[str] = Field(default_factory=list)
    summary: str = ""


def slugify(text: str) -> str:
    """Turn arbitrary text into a safe, stable slug."""
    lowered = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return lowered[:48] or "project"


def canonical_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def fingerprint(model: BaseModel) -> str:
    return hashlib.sha256(canonical_json(model).encode()).hexdigest()[:16]


MODELS: dict[str, type[BaseModel]] = {
    "IdeaBrief": IdeaBrief,
    "Requirements": Requirements,
    "Architecture": Architecture,
    "TaskPlan": TaskPlan,
    "BuildResult": BuildResult,
    "TestReport": TestReport,
    "Review": Review,
    "RunReport": RunReport,
}
