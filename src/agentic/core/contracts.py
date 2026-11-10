"""JSON Schema 2020-12 generation and validation.

The Pydantic models in :mod:`agentic.core.spec` are the source of truth; this
module publishes them as standalone JSON Schema documents under ``schemas/`` so
that non-Python agents can validate the exact same contracts, and validates
incoming payloads against them before anything is trusted.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ..errors import ContractError
from .spec import MODELS

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"
SCHEMA_BASE_URI = "https://agentic.dev/schemas"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def schema_dir() -> Path:
    """Locate the committed schema directory, falling back to the repo root."""
    for candidate in (SCHEMA_DIR, _repo_root() / "schemas"):
        if candidate.is_dir():
            return candidate
    return SCHEMA_DIR


def generate_schemas(out_dir: Path | None = None) -> list[Path]:
    """Emit one JSON Schema 2020-12 document per artifact model."""
    target = out_dir or schema_dir()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        # Self-contained schemas: definitions are inlined as #/$defs so a single
        # file is enough for any validator in any language, no resolver needed.
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"{SCHEMA_BASE_URI}/{name}.schema.json"
        schema["x-agentic-artifact"] = name
        path = target / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, Any]]:
    """All published schemas, keyed by $id and by bare name."""
    registry: dict[str, dict[str, Any]] = {}
    directory = schema_dir()
    if directory.is_dir():
        for path in sorted(directory.glob("*.schema.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if "$id" in doc:
                registry[doc["$id"]] = doc
            registry[path.name] = doc
            registry[path.stem.replace(".schema", "")] = doc
    return registry


def schema_for(name: str) -> dict[str, Any]:
    """Return the published JSON Schema for an artifact name."""
    registry = _registry()
    doc = registry.get(name) or registry.get(f"{name}.schema.json")
    if doc is None:
        raise ContractError(f"no published schema for artifact {name!r}")
    return doc


def _validator(name: str) -> Draft202012Validator:
    schema = schema_for(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_payload(name: str, payload: Any) -> None:
    """Raise :class:`ContractError` if ``payload`` violates the artifact schema."""
    validator = _validator(name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        rendered = [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors[:12]
        ]
        raise ContractError(f"{name} failed JSON Schema validation", errors=rendered)


def validation_errors(name: str, payload: Any) -> list[str]:
    """Non-raising variant used to feed model repair prompts."""
    try:
        validator = _validator(name)
    except ContractError as exc:
        return [str(exc)]
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    ]
