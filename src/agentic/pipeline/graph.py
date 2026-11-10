"""The stage graph.

A declarative description of the pipeline. The orchestrator walks it, so the
shape of the process is data — you can read the whole workflow in one table and
reorder or extend stages without touching control flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageDef:
    name: str
    agent: str
    inputs: tuple[str, ...] = ()
    output: str | None = None
    tools: tuple[str, ...] = ()
    optional: bool = False
    """`optional` stages run best-effort: their failure is recorded, not fatal."""


PIPELINE: tuple[StageDef, ...] = (
    StageDef(name="scout", agent="scout", inputs=("idea",), output="IdeaBrief"),
    StageDef(name="analyst", agent="analyst", inputs=("IdeaBrief",), output="Requirements"),
    StageDef(name="architect", agent="architect", inputs=("Requirements",), output="Architecture"),
    StageDef(name="planner", agent="planner", inputs=("Architecture", "Requirements"), output="TaskPlan"),
    StageDef(name="build", agent="builder", inputs=("TaskItem", "Architecture", "Requirements"), output="BuildResult", tools=("workspace",)),
    StageDef(name="verify", agent="verifier", inputs=(), output="TestReport", tools=("sandbox",)),
    StageDef(name="review", agent="reviewer", inputs=("Requirements", "TestReport"), output="Review"),
)

BY_NAME: dict[str, StageDef] = {stage.name: stage for stage in PIPELINE}


def next_stage(current: str) -> StageDef | None:
    """Return the stage following ``current``, or None at the end."""
    for index, stage in enumerate(PIPELINE):
        if stage.name == current and index + 1 < len(PIPELINE):
            return PIPELINE[index + 1]
    return None


def stages_requiring(tool: str) -> list[str]:
    return [s.name for s in PIPELINE if tool in s.tools]


@dataclass
class RunState:
    """Mutable bag of artifacts keyed by artifact name."""

    artifacts: dict[str, object] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)

    def put(self, name: str, value: object) -> None:
        self.artifacts[name] = value
        self.history.append(name)

    def get(self, name: str) -> object | None:
        return self.artifacts.get(name)

    def require(self, *names: str) -> dict[str, object]:
        missing = [n for n in names if n not in self.artifacts]
        if missing:
            raise KeyError(f"missing artifacts: {', '.join(missing)}")
        return {n: self.artifacts[n] for n in names}
