"""Deterministic offline LLM.

Lets the whole pipeline run with zero API keys. It reads the ``AGENTIC-STAGE``
marker and the embedded artifact blocks from the prompt and answers with
schema-valid JSON. Builder answers come from the real code generator in
:mod:`agentic.agents.codegen`, so mock mode produces a genuinely working,
genuinely tested project.

Set ``AGENTIC_MOCK_FAULTS=1`` to inject a deliberate bug on the first build so
the verify -> review -> fix loop has something real to repair.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..agents.codegen import python_package, render_project
from .base import ChatMessage, LLMResponse, ToolSpec

ARTIFACT_RE = re.compile(r"<<<ARTIFACT:(?P<name>[A-Za-z]+)\n(?P<body>.*?)\nARTIFACT>>>", re.DOTALL)
STAGE_RE = re.compile(r"AGENTIC-STAGE:\s*([a-z_]+)")


def parse_stage(messages: list[ChatMessage]) -> str:
    for message in messages:
        match = STAGE_RE.search(message.content)
        if match:
            return match.group(1)
    return ""


def parse_artifacts(messages: list[ChatMessage]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for message in messages:
        for match in ARTIFACT_RE.finditer(message.content):
            try:
                found[match.group("name")] = json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
    return found


def raw_idea(messages: list[ChatMessage]) -> str:
    for message in messages:
        if message.role == "user":
            match = re.search(r"IDEA:\s*(.+?)\s*(?:\n\s*\n|$)", message.content, re.DOTALL)
            if match:
                return match.group(1).strip()[:600]
    return "a small command line utility"


class MockLLM:
    """Stage-aware deterministic responder."""

    name = "mock"

    def __init__(self, *, inject_faults: bool | None = None) -> None:
        if inject_faults is None:
            inject_faults = os.environ.get("AGENTIC_MOCK_FAULTS", "").lower() in {"1", "true", "yes"}
        self.inject_faults = inject_faults

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stage: str = "",
    ) -> LLMResponse:
        resolved = stage or parse_stage(messages)
        artifacts = parse_artifacts(messages)
        handler = getattr(self, f"_stage_{resolved}", None)
        if handler is None:
            payload: dict[str, Any] = {"ok": True, "stage": resolved, "note": "mock passthrough"}
        else:
            payload = handler(messages, artifacts)
        return LLMResponse(
            content=json.dumps(payload, sort_keys=True),
            model="agentic-mock",
            finish_reason="stop",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    # -- stages ----------------------------------------------------------

    def _stage_scout(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        idea = raw_idea(messages)
        words = [w for w in re.findall(r"[A-Za-z]{4,}", idea.lower())]
        title = " ".join(dict.fromkeys(words[:4])).title() or "Utility Project"
        return {
            "schema_version": "1",
            "title": title[:120],
            "one_liner": f"A focused tool that delivers: {idea[:160]}",
            "problem": (
                f"Today the work described as '{idea[:200]}' is done by hand, which is slow, "
                "inconsistent and hard to verify. There is no single place to run it, test it or reuse it."
            ),
            "users": ["operators who run it repeatedly", "developers who extend it"],
            "value": "Turns an ad-hoc manual chore into a tested, scripted, repeatable command.",
            "constraints": ["must run offline", "no external services", "must be testable in CI"],
            "out_of_scope": ["web UI", "multi-user auth", "deployment automation"],
            "assumptions": ["users have Python 3.11+", "input arrives as plain text"],
            "success_metrics": [
                "a single command performs the task end to end",
                "every functional requirement has a passing test",
            ],
        }

    def _stage_analyst(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        brief = artifacts.get("IdeaBrief", {})
        title = brief.get("title", "Utility Project")
        problem = brief.get("problem", "")
        project = python_package(title)
        seeds = [
            ("normalise and validate the incoming text before any processing happens", "functional"),
            ("compute the primary numeric result the operator asked for", "functional"),
            ("expose every capability as a command line subcommand", "functional"),
            ("report failures as clear messages on stderr with a non-zero exit code", "functional"),
            ("keep every core routine a pure function so it can be unit tested", "non-functional"),
            ("finish the full test suite in under ten seconds", "non-functional"),
        ]
        requirements = []
        fr = nfr = 0
        for text, kind in seeds:
            if kind == "functional":
                fr += 1
                req_id = f"FR-{fr:03d}"
            else:
                nfr += 1
                req_id = f"NFR-{nfr:03d}"
            requirements.append(
                {
                    "id": req_id,
                    "kind": kind,
                    "title": text.split(" ")[0].title() + ": " + text[:60],
                    "description": f"{title} shall {text}. Context: {problem[:120]}",
                    "rationale": "Derived from the idea brief during analysis.",
                    "acceptance_criteria": [
                        f"a test exists that exercises {req_id} and passes",
                        f"behaviour for {req_id} is documented in the README",
                    ],
                    "priority": "must" if kind == "functional" else "should",
                }
            )
        return {
            "schema_version": "1",
            "project_name": project,
            "summary": f"{title}: {brief.get('one_liner', '')}"[:400],
            "requirements": requirements,
            "open_questions": ["should output support JSON as well as plain text?"],
        }

    def _stage_architect(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        reqs = artifacts.get("Requirements", {})
        project = python_package(reqs.get("project_name", "app"))
        fr_ids = [r["id"] for r in reqs.get("requirements", []) if r.get("kind") == "functional"]
        return {
            "schema_version": "1",
            "stack": {
                "language": "python",
                "runtime": "cpython>=3.11",
                "framework": "none",
                "build_tool": "hatch",
                "test_framework": "pytest",
                "package_manager": "uv",
                "dependencies": [],
            },
            "overview": (
                "A small layered package: pure functions in a core module, a thin argparse CLI on top, "
                "and a pytest suite that pins every functional requirement."
            ),
            "components": [
                {
                    "id": "core",
                    "name": "Core logic",
                    "responsibility": "Pure, side-effect-free functions implementing each functional requirement.",
                    "modules": [
                        {
                            "path": f"{project}/core.py",
                            "purpose": "One function per functional requirement.",
                            "symbols": [],
                        }
                    ],
                    "depends_on": [],
                    "requirement_ids": fr_ids,
                },
                {
                    "id": "cli",
                    "name": "Command line interface",
                    "responsibility": "Parse arguments, call core, format results, map errors to exit codes.",
                    "modules": [
                        {
                            "path": f"{project}/cli.py",
                            "purpose": "argparse subcommands delegating to core.",
                            "symbols": ["main", "build_parser"],
                        },
                        {
                            "path": f"{project}/__main__.py",
                            "purpose": "python -m entry point.",
                            "symbols": [],
                        },
                    ],
                    "depends_on": ["core"],
                    "requirement_ids": fr_ids,
                },
                {
                    "id": "tests",
                    "name": "Test suite",
                    "responsibility": "Executable proof that each functional requirement is met.",
                    "modules": [
                        {"path": "tests/test_core.py", "purpose": "One test per core function.", "symbols": []}
                    ],
                    "depends_on": ["core"],
                    "requirement_ids": fr_ids,
                },
            ],
            "entry_points": [
                {
                    "name": "cli",
                    "kind": "cli",
                    "invocation": f"python -m {project} <command>",
                    "description": "Operator-facing command line entry point.",
                }
            ],
            "data_flow": ["argv -> cli.main -> core function -> stdout / exit code"],
            "decisions": [
                "No third-party runtime dependencies: keeps install fast and the attack surface small.",
                "Core stays pure so the test suite needs no fixtures or mocking.",
            ],
            "risks": ["CLI argument parsing must not swallow real errors"],
        }

    def _stage_planner(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        reqs = artifacts.get("Requirements", {})
        arch = artifacts.get("Architecture", {})
        project = python_package(reqs.get("project_name", "app"))
        fr_ids = [r["id"] for r in reqs.get("requirements", []) if r.get("kind") == "functional"]
        generated = render_project(
            project,
            reqs.get("project_name", project),
            reqs.get("summary", ""),
            [r.get("description", "") for r in reqs.get("requirements", [])],
            fr_ids,
        )
        buildable = generated.paths()
        chunks = _split_even(buildable, max(2, min(4, len(buildable))))
        tasks = []
        for index, files in enumerate(chunks, start=1):
            tasks.append(
                {
                    "id": f"task-{index}",
                    "title": f"Implement {', '.join(p.split('/')[-1] for p in files)}",
                    "description": (
                        f"Write {', '.join(files)} so the architecture contract is satisfied and the "
                        "generated tests pass."
                    ),
                    "component_ids": ["core", "cli", "tests"],
                    "target_files": files,
                    "depends_on": [] if index == 1 else [f"task-{index - 1}"],
                    "requirement_ids": fr_ids or ["FR-001"],
                    "done_when": ["file exists on disk", "pytest passes"],
                }
            )
        return {"schema_version": "1", "goal": reqs.get("summary", "build the project")[:300], "tasks": tasks}

    def _stage_builder(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        reqs = artifacts.get("Requirements", {})
        task = artifacts.get("TaskItem", {})
        project = python_package(reqs.get("project_name", "app"))
        fr_ids = [r["id"] for r in reqs.get("requirements", []) if r.get("kind") == "functional"]
        generated = render_project(
            project,
            reqs.get("project_name", project),
            reqs.get("summary", ""),
            [r.get("description", "") for r in reqs.get("requirements", [])],
            fr_ids,
        )
        target = list(task.get("target_files") or [])
        paths = [p for p in target if p in generated.files] or generated.paths()
        repairing = "REPAIR REQUESTED" in _all_text(messages)
        inject = self.inject_faults and not repairing and "core.py" in " ".join(paths)
        files = []
        for path in paths:
            content = generated.files[path]
            if inject and path.endswith("core.py"):
                content = _inject_fault(content)
            files.append({"path": path, "action": "create", "content": content})
        notes = "Generated from the architecture contract."
        if inject:
            notes += " [fault injected for loop verification]"
        return {
            "schema_version": "1",
            "task_id": task.get("id", "task-1"),
            "status": "ok",
            "files": files,
            "notes": notes,
            "deviations": [],
            "follow_ups": [],
        }

    def _stage_reviewer(self, messages: list[ChatMessage], artifacts: dict[str, Any]) -> dict[str, Any]:
        report = artifacts.get("TestReport", {})
        failed = int(report.get("failed", 0) or 0)
        errors = int(report.get("errors", 0) or 0)
        findings: list[dict[str, Any]] = []
        if failed or errors:
            findings.append(
                {
                    "id": "f-1",
                    "severity": "blocker",
                    "category": "correctness",
                    "location": "tests",
                    "description": f"{failed} test(s) failed and {errors} errored; the build is not releasable.",
                    "suggested_fix": "Repair the implementation so the suite is green.",
                }
            )
        else:
            findings.append(
                {
                    "id": "f-1",
                    "severity": "info",
                    "category": "maintainability",
                    "location": "core",
                    "description": "Core functions are pure and covered; consider adding property tests later.",
                    "suggested_fix": "Optional: add hypothesis property tests in a follow-up.",
                }
            )
        return {
            "schema_version": "1",
            "verdict": "request_changes" if findings and findings[0]["severity"] == "blocker" else "approve",
            "summary": (
                "Suite is green and the architecture contract holds."
                if not failed and not errors
                else "Suite is red; changes requested."
            ),
            "findings": findings,
        }


def _all_text(messages: list[ChatMessage]) -> str:
    return "\n".join(m.content for m in messages)


def _inject_fault(core: str) -> str:
    """Introduce a subtle, deterministic bug into generated core code."""
    if "return len(text.split())" in core:
        return core.replace("return len(text.split())", "return max(0, len(text.split()) - 1)", 1)
    if "return float(sum(values))" in core:
        return core.replace("return float(sum(values))", "return float(sum(values)) * 2", 1)
    lines = core.split("\n")
    for index, line in enumerate(lines):
        if line.strip().startswith("return ") and index > 6:
            lines[index] = line.replace("return ", "return 0 if False else ", 1)
            break
    return "\n".join(lines)


def _split_even(items: list[str], parts: int) -> list[list[str]]:
    if not items:
        return [[]]
    parts = max(1, min(parts, len(items)))
    size, remainder = divmod(len(items), parts)
    out: list[list[str]] = []
    start = 0
    for index in range(parts):
        extra = 1 if index < remainder else 0
        out.append(items[start : start + size + extra])
        start += size + extra
    return [chunk for chunk in out if chunk]
