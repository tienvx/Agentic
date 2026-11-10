"""Agent registry: the catalogue the orchestrator and the A2A service use."""

from __future__ import annotations

from ..a2a.models import AgentCard
from ..core.events import EventBus
from ..llm.base import LLMClient
from .base import StageAgent
from .stages import (
    AnalystAgent,
    ArchitectAgent,
    BuilderAgent,
    IdeaScoutAgent,
    PlannerAgent,
    ReviewerAgent,
    VerifierAgent,
)

AGENT_TYPES: tuple[type[StageAgent], ...] = (
    IdeaScoutAgent,
    AnalystAgent,
    ArchitectAgent,
    PlannerAgent,
    BuilderAgent,
    VerifierAgent,
    ReviewerAgent,
)

BY_STAGE: dict[str, type[StageAgent]] = {cls.stage: cls for cls in AGENT_TYPES}


def build_agent(stage: str, llm: LLMClient, events: EventBus | None = None) -> StageAgent:
    try:
        cls = BY_STAGE[stage]
    except KeyError as exc:
        raise KeyError(f"unknown stage {stage!r}; known: {', '.join(sorted(BY_STAGE))}") from exc
    return cls(llm, events)


def build_all_agents(llm: LLMClient, events: EventBus | None = None) -> dict[str, StageAgent]:
    return {stage: cls(llm, events) for stage, cls in BY_STAGE.items()}


def card_for(agent: StageAgent, url: str) -> AgentCard:
    return agent.card(url)


def catalogue() -> list[dict[str, object]]:
    """Machine-readable summary used by ``agentic agents``."""
    return [
        {
            "stage": cls.stage,
            "agent_id": cls.agent_id,
            "name": cls.display_name,
            "description": cls.description,
            "output": cls.output_model.__name__,
            "requires": list(cls.requires),
            "tools": list(cls.uses_tools),
            "tags": list(cls.tags),
        }
        for cls in AGENT_TYPES
    ]
