"""Artifact contracts: JSON Schema generation and validation."""

from __future__ import annotations

import json

import pytest

from agentic.core.contracts import generate_schemas, schema_for, validate_payload, validation_errors
from agentic.core.spec import (
    Architecture,
    IdeaBrief,
    Requirements,
    Review,
    TaskItem,
    TaskPlan,
    TestReport,
)

GOOD_BRIEF = {
    "schema_version": "1",
    "title": "Invoice Tally",
    "one_liner": "Totals invoice line items from the command line.",
    "problem": "Invoices are totalled by hand in spreadsheets, which is slow and error prone.",
    "users": ["bookkeepers"],
    "value": "One command produces a correct total.",
    "constraints": ["offline"],
    "out_of_scope": ["web UI"],
    "assumptions": ["amounts are integers of cents"],
    "success_metrics": ["pytest passes"],
}


def test_generate_schemas_emits_every_artifact(tmp_path) -> None:
    written = generate_schemas(tmp_path)
    names = {p.name for p in written}
    assert {
        "IdeaBrief.schema.json",
        "Requirements.schema.json",
        "Architecture.schema.json",
        "TaskPlan.schema.json",
        "BuildResult.schema.json",
        "TestReport.schema.json",
        "Review.schema.json",
        "RunReport.schema.json",
    } == names


def test_schemas_are_draft_2020_12_and_self_contained(tmp_path) -> None:
    for path in generate_schemas(tmp_path):
        doc = json.loads(path.read_text())
        assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert doc["$id"].endswith(".schema.json")
        # No external refs: a single file must be enough for any validator.
        text = path.read_text()
        assert '"$ref": "http' not in text.replace("$ref\": \"https://json-schema.org", "")


def test_valid_brief_passes() -> None:
    validate_payload("IdeaBrief", GOOD_BRIEF)


def test_missing_required_field_is_reported() -> None:
    payload = dict(GOOD_BRIEF)
    del payload["one_liner"]
    errors = validation_errors("IdeaBrief", payload)
    assert errors and any("one_liner" in e for e in errors)


def test_unknown_field_is_rejected() -> None:
    payload = dict(GOOD_BRIEF, surprise="nope")
    assert validation_errors("IdeaBrief", payload)


def test_brief_slug() -> None:
    assert IdeaBrief.model_validate(GOOD_BRIEF).slug == "invoice-tally"


def test_requirement_id_format() -> None:
    with pytest.raises(ValueError, match="FR-NNN"):
        TaskItem  # noqa: B018 - import smoke check
        Requirements.model_validate(
            {
                "project_name": "app",
                "summary": "A tool that does a useful thing for operators.",
                "requirements": [
                    {
                        "id": "REQ-1",
                        "kind": "functional",
                        "title": "Do the thing",
                        "description": "The system shall do the thing that operators need done.",
                        "acceptance_criteria": ["a test exercises the thing and passes"],
                    }
                ],
            }
        )


def test_requirements_need_a_functional_one() -> None:
    with pytest.raises(ValueError, match="functional"):
        Requirements.model_validate(
            {
                "project_name": "app",
                "summary": "A tool that does a useful thing for operators.",
                "requirements": [
                    {
                        "id": "NFR-001",
                        "kind": "non-functional",
                        "title": "Be fast",
                        "description": "The system shall complete the test suite in under ten seconds.",
                        "acceptance_criteria": ["the suite finishes in under ten seconds"],
                    }
                ],
            }
        )


def test_vague_acceptance_criteria_rejected() -> None:
    with pytest.raises(ValueError, match="specific"):
        Requirements.model_validate(
            {
                "project_name": "app",
                "summary": "A tool that does a useful thing for operators.",
                "requirements": [
                    {
                        "id": "FR-001",
                        "kind": "functional",
                        "title": "Do the thing",
                        "description": "The system shall do the thing that operators need done daily.",
                        "acceptance_criteria": ["ok"],
                    }
                ],
            }
        )


def _task(task_id: str, deps: list[str]) -> dict:
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "description": f"Implement {task_id} so the architecture contract is satisfied.",
        "component_ids": ["core"],
        "target_files": [f"app/{task_id}.py"],
        "depends_on": deps,
        "requirement_ids": ["FR-001"],
        "done_when": ["pytest passes"],
    }


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        TaskPlan.model_validate(
            {"goal": "Build the thing", "tasks": [_task("a", ["b"]), _task("b", ["a"])]}
        )


def test_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(ValueError, match="unknown task"):
        TaskPlan.model_validate({"goal": "Build the thing", "tasks": [_task("a", ["ghost"])]})


def test_plan_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        TaskItem.model_validate(
            {
                "id": "a",
                "title": "Task a",
                "description": "Implement a so the architecture contract is satisfied.",
                "component_ids": ["core"],
                "target_files": ["/etc/passwd"],
                "depends_on": [],
                "requirement_ids": ["FR-001"],
                "done_when": ["pytest passes"],
            }
        )


def test_build_order_is_topological_and_deterministic() -> None:
    plan = TaskPlan.model_validate(
        {
            "goal": "Build the thing",
            "tasks": [_task("c", ["b"]), _task("a", []), _task("b", ["a"])],
        }
    )
    assert plan.build_order() == ["a", "b", "c"]
    assert plan.build_order() == ["a", "b", "c"]


def test_architecture_rejects_unknown_component_dependency() -> None:
    with pytest.raises(ValueError, match="unknown"):
        Architecture.model_validate(
            {
                "overview": "A layered package with a core module and a CLI on top of it.",
                "components": [
                    {
                        "id": "cli",
                        "name": "CLI",
                        "responsibility": "Parse arguments and call the core module.",
                        "modules": [{"path": "app/cli.py", "purpose": "entry point"}],
                        "depends_on": ["ghost"],
                    }
                ],
                "entry_points": [{"name": "cli", "kind": "cli", "invocation": "python -m app"}],
            }
        )


def test_test_report_defaults_to_failure() -> None:
    report = TestReport(task_id="all", command="pytest -q")
    assert report.success is False


def test_review_blocking_findings() -> None:
    review = Review.model_validate(
        {
            "verdict": "request_changes",
            "summary": "The suite is red so this cannot ship.",
            "findings": [
                {"id": "f-1", "severity": "blocker", "description": "Two tests fail on the happy path."},
                {"id": "f-2", "severity": "minor", "description": "Naming could be clearer in core."},
            ],
        }
    )
    assert [f.id for f in review.blocking] == ["f-1"]


def test_schema_for_unknown_name_raises() -> None:
    from agentic.errors import ContractError

    with pytest.raises(ContractError):
        schema_for("NoSuchArtifact")
