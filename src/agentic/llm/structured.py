"""Schema-constrained generation with a bounded repair loop.

This is the reliability core: a model's answer is not accepted until it passes
(a) JSON Schema 2020-12 validation against the published artifact contract and
(b) Pydantic semantic validation. Failures are turned into a precise repair
prompt and fed back, up to ``AGENTIC_REPAIR_ATTEMPTS`` times.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..core.contracts import validation_errors
from ..core.events import Event, EventBus
from ..errors import ContractError, LLMError
from .base import ChatMessage, LLMClient

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the first complete JSON object out of a model reply."""
    if not text or not text.strip():
        raise ContractError("model returned an empty response")
    candidates: list[str] = []
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1))
    candidates.append(text)
    # Balanced-brace scan as a last resort (handles prose around the object).
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
    last_error: Exception | None = None
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        last_error = ContractError(f"expected a JSON object, got {type(parsed).__name__}")
    raise ContractError(f"no JSON object found in model reply: {last_error}")


async def ask_structured(
    llm: LLMClient,
    *,
    stage: str,
    system: str,
    user: str,
    model_cls: type[M],
    schema_name: str | None = None,
    events: EventBus | None = None,
    max_repairs: int | None = None,
    temperature: float | None = None,
) -> M:
    """Ask ``llm`` for an instance of ``model_cls``, repairing until valid."""
    schema_name = schema_name or model_cls.__name__
    attempts = (get_settings().repair_attempts if max_repairs is None else max_repairs) + 1
    schema = json.dumps(model_cls.model_json_schema(), sort_keys=True)
    messages = [
        ChatMessage(
            role="system",
            content=(
                f"AGENTIC-STAGE: {stage}\n\n{system.strip()}\n\n"
                "Respond with a SINGLE JSON object and nothing else. It MUST validate against this "
                f"JSON Schema (draft 2020-12):\n{schema}"
            ),
        ),
        ChatMessage(role="user", content=user),
    ]

    last_error = ""
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        response = await llm.complete(messages, json_mode=True, temperature=temperature, stage=stage)
        elapsed = time.perf_counter() - started
        try:
            payload = extract_json(response.content)
        except ContractError as exc:
            last_error = str(exc)
            _emit(events, stage, llm.name, f"unparseable reply (attempt {attempt})", elapsed)
            messages = _append_repair(messages, response.content, [last_error])
            continue

        schema_errors = validation_errors(schema_name, payload)
        if schema_errors:
            last_error = "; ".join(schema_errors)
            _emit(events, stage, llm.name, f"schema violation (attempt {attempt})", elapsed)
            messages = _append_repair(messages, response.content, schema_errors)
            continue

        try:
            instance = model_cls.model_validate(payload)
        except ValidationError as exc:
            errors = [
                f"{'/'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()[:12]
            ]
            last_error = "; ".join(errors)
            _emit(events, stage, llm.name, f"semantic violation (attempt {attempt})", elapsed)
            messages = _append_repair(messages, response.content, errors)
            continue

        _emit(events, stage, llm.name, f"valid {schema_name} (attempt {attempt})", elapsed)
        return instance

    raise LLMError(f"stage {stage!r}: could not obtain a valid {schema_name} after {attempts} attempts: {last_error}")


def _append_repair(messages: list[ChatMessage], previous: str, errors: list[str]) -> list[ChatMessage]:
    repair = (
        "REPAIR REQUESTED\nYour previous reply failed validation. Errors:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\nReturn the COMPLETE corrected JSON object only. Do not add commentary."
    )
    return messages + [
        ChatMessage(role="assistant", content=previous[:4000]),
        ChatMessage(role="user", content=repair),
    ]


def _emit(events: EventBus | None, stage: str, agent: str, message: str, elapsed: float) -> None:
    if events is None:
        return
    events.emit(
        Event(
            kind="llm",
            stage=stage,
            agent=agent,
            message=message,
            data={"duration_s": round(elapsed, 3)},
        )
    )
