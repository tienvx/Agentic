"""Base class shared by every stage agent.

An agent is: a skill description (for its A2A Agent Card), a prompt builder,
and a contract (the Pydantic model it must return). Everything else — LLM
selection, schema validation, repair, retries — comes from the shared plumbing.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from ..a2a.models import AgentCard, AgentSkill, new_agent_card
from ..core.events import EventBus
from ..llm.base import LLMClient
from ..llm.structured import ask_structured

MAX_BLOCK_CHARS = 24_000


def format_artifact(name: str, value: Any) -> str:
    """Render an artifact as a delimited JSON block the mock can also parse."""
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = value
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if len(text) > MAX_BLOCK_CHARS:
        text = text[:MAX_BLOCK_CHARS] + "\n... truncated ..."
    return f"<<<ARTIFACT:{name}\n{text}\nARTIFACT>>>"


def artifact_block(artifacts: dict[str, Any]) -> str:
    if not artifacts:
        return "(none)"
    return "\n\n".join(format_artifact(name, value) for name, value in artifacts.items())


@dataclass
class AgentOutput:
    """What an agent returns: the validated model plus a trace of what happened."""

    model: BaseModel
    stage: str
    attempts: int = 1
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return type(self.model).__name__


class StageAgent(ABC):
    """An agent that turns upstream artifacts into one validated artifact."""

    stage: ClassVar[str] = ""
    agent_id: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    tags: ClassVar[tuple[str, ...]] = ()
    output_model: ClassVar[type[BaseModel]]
    requires: ClassVar[tuple[str, ...]] = ()
    uses_tools: ClassVar[tuple[str, ...]] = ()

    def __init__(self, llm: LLMClient, events: EventBus | None = None) -> None:
        self.llm = llm
        self.events = events

    # -- prompts ---------------------------------------------------------

    @abstractmethod
    def system_prompt(self) -> str:
        """Role and rules for this stage."""

    def user_prompt(self, inputs: dict[str, Any]) -> str:
        """Default: hand the upstream artifacts over verbatim."""
        return f"Upstream artifacts:\n\n{artifact_block(inputs)}"

    # -- execution -------------------------------------------------------

    async def produce(self, inputs: dict[str, Any], **kwargs: Any) -> BaseModel:
        missing = [key for key in self.requires if key not in inputs]
        if missing:
            raise ValueError(f"{self.stage}: missing required inputs {missing}")
        return await ask_structured(
            self.llm,
            stage=self.stage,
            system=self.system_prompt(),
            user=self.user_prompt(inputs),
            model_cls=self.output_model,
            events=self.events,
            **kwargs,
        )

    # -- A2A surface -----------------------------------------------------

    def skill(self) -> AgentSkill:
        return AgentSkill(
            id=self.stage,
            name=self.display_name or self.stage,
            description=self.description,
            tags=list(self.tags) or [self.stage],
            input_modes=["application/json", "text/plain"],
            output_modes=["application/json"],
            examples=[f"Produce a {self.output_model.__name__}."],
        )

    def card(self, url: str) -> AgentCard:
        return new_agent_card(
            name=self.display_name or self.agent_id,
            description=self.description,
            url=url,
            skills=[self.skill()],
            version="0.1.0",
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} stage={self.stage} llm={self.llm.name}>"
