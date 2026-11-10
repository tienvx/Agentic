"""Agents: one per pipeline stage, each also publishable as an A2A server."""

from __future__ import annotations

from .base import AgentOutput, StageAgent, artifact_block, format_artifact
from .registry import AGENT_TYPES, build_agent, build_all_agents, card_for
from .stages import (
    AnalystAgent,
    ArchitectAgent,
    BuilderAgent,
    IdeaScoutAgent,
    PlannerAgent,
    ReviewerAgent,
    VerifierAgent,
)

__all__ = [
    "AGENT_TYPES",
    "AgentOutput",
    "AnalystAgent",
    "ArchitectAgent",
    "BuilderAgent",
    "IdeaScoutAgent",
    "PlannerAgent",
    "ReviewerAgent",
    "StageAgent",
    "VerifierAgent",
    "artifact_block",
    "build_agent",
    "build_all_agents",
    "card_for",
    "format_artifact",
]
