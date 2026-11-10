"""A2A v1.0.0 canonical data model as Pydantic types.

Field names use the ProtoJSON camelCase spelling via aliases, and enums use the
``TASK_STATE_*`` / ``ROLE_*`` names the reference protobuf emits, so documents
produced here parse cleanly with ``google.protobuf.json_format``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

A2A_PROTOCOL_VERSION = "1.0"
AGENT_CARD_PATH = "/.well-known/agent-card.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WireModel(BaseModel):
    """Base that serialises with camelCase aliases and ProtoJSON-style omission."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore", validate_by_alias=True)

    def to_wire(self) -> dict[str, Any]:
        """ProtoJSON-ish dict: camelCase keys, empty collections and None dropped."""
        return _prune(self.model_dump(by_alias=True, exclude_none=True, mode="json"))


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        pruned = {k: _prune(v) for k, v in value.items() if v is not None}
        return {k: v for k, v in pruned.items() if v != [] and v != {}}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskState(str, Enum):
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELED,
            TaskState.REJECTED,
        }

    @property
    def is_interrupted(self) -> bool:
        return self in {TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED}


class Role(str, Enum):
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


# ---------------------------------------------------------------------------
# Core objects
# ---------------------------------------------------------------------------


class Part(WireModel):
    """Smallest unit of content. Exactly one of text / raw / url / data is set."""

    text: str | None = None
    raw: str | None = None  # base64, per ProtoJSON bytes encoding
    url: str | None = None
    data: Any | None = None
    metadata: dict[str, Any] | None = None
    filename: str | None = None
    media_type: str | None = Field(default=None, alias="mediaType")

    @property
    def content_kind(self) -> Literal["text", "raw", "url", "data", "empty"]:
        for kind in ("text", "raw", "url", "data"):
            if getattr(self, kind) is not None:
                return kind  # type: ignore[return-value]
        return "empty"

    def as_text(self) -> str:
        if self.text is not None:
            return self.text
        if self.data is not None:
            import json

            return json.dumps(self.data, sort_keys=True)
        if self.url is not None:
            return self.url
        return ""


class Message(WireModel):
    message_id: str = Field(default_factory=lambda: uuid4().hex, alias="messageId")
    context_id: str | None = Field(default=None, alias="contextId")
    task_id: str | None = Field(default=None, alias="taskId")
    role: Role = Role.AGENT
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None
    reference_task_ids: list[str] | None = Field(
        default=None, alias="referenceTaskIds"
    )

    @property
    def text(self) -> str:
        return "\n".join(p.as_text() for p in self.parts if p.content_kind in ("text", "data"))


class Artifact(WireModel):
    artifact_id: str = Field(default_factory=lambda: uuid4().hex, alias="artifactId")
    name: str | None = None
    description: str | None = None
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None


class TaskStatus(WireModel):
    state: TaskState = TaskState.SUBMITTED
    message: Message | None = None
    timestamp: str = Field(default_factory=_now)


class Task(WireModel):
    id: str
    context_id: str | None = Field(default=None, alias="contextId")
    status: TaskStatus = Field(default_factory=TaskStatus)
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


class TaskStatusUpdateEvent(WireModel):
    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    status: TaskStatus
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(WireModel):
    task_id: str = Field(alias="taskId")
    context_id: str = Field(alias="contextId")
    artifact: Artifact
    append: bool | None = None
    last_chunk: bool | None = Field(default=None, alias="lastChunk")
    metadata: dict[str, Any] | None = None


class StreamResponse(WireModel):
    """Oneof wrapper used by streaming and push notification payloads."""

    task: Task | None = None
    message: Message | None = None
    status_update: TaskStatusUpdateEvent | None = Field(
        default=None, alias="statusUpdate"
    )
    artifact_update: TaskArtifactUpdateEvent | None = Field(
        default=None, alias="artifactUpdate"
    )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class TaskPushNotificationConfig(WireModel):
    tenant: str | None = None
    id: str | None = None
    task_id: str | None = Field(default=None, alias="taskId")
    url: str | None = None
    token: str | None = None
    authentication: dict[str, Any] | None = None


class SendMessageConfiguration(WireModel):
    accepted_output_modes: list[str] | None = Field(
        default=None, alias="acceptedOutputModes"
    )
    task_push_notification_config: TaskPushNotificationConfig | None = Field(
        default=None, alias="taskPushNotificationConfig"
    )
    history_length: int | None = Field(default=None, alias="historyLength")
    return_immediately: bool | None = Field(
        default=None, alias="returnImmediately"
    )


class SendMessageRequest(WireModel):
    tenant: str | None = None
    message: Message
    configuration: SendMessageConfiguration | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


class AgentExtension(WireModel):
    uri: str
    description: str | None = None
    required: bool | None = None
    params: dict[str, Any] | None = None


class AgentCapabilities(WireModel):
    streaming: bool | None = None
    push_notifications: bool | None = Field(
        default=None, alias="pushNotifications"
    )
    extensions: list[AgentExtension] | None = None
    extended_agent_card: bool | None = Field(
        default=None, alias="extendedAgentCard"
    )


class AgentSkill(WireModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    input_modes: list[str] | None = Field(default=None, alias="inputModes")
    output_modes: list[str] | None = Field(default=None, alias="outputModes")
    security_requirements: list[dict[str, Any]] | None = Field(
        default=None, alias="securityRequirements"
    )


class AgentProvider(WireModel):
    url: str
    organization: str


class AgentInterface(WireModel):
    url: str
    protocol_binding: str = Field(
        default="JSONRPC", alias="protocolBinding"
    )
    tenant: str | None = None
    protocol_version: str = Field(
        default=A2A_PROTOCOL_VERSION, alias="protocolVersion"
    )


class AgentCard(WireModel):
    name: str
    description: str
    supported_interfaces: list[AgentInterface] = Field(
        default_factory=list, alias="supportedInterfaces"
    )
    provider: AgentProvider | None = None
    version: str = "0.1.0"
    documentation_url: str | None = Field(default=None, alias="documentationUrl")
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    security_schemes: dict[str, dict[str, Any]] | None = Field(
        default=None, alias="securitySchemes"
    )
    security_requirements: list[dict[str, Any]] | None = Field(
        default=None, alias="securityRequirements"
    )
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"],
        alias="defaultInputModes",
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["application/json"],
        alias="defaultOutputModes",
    )
    skills: list[AgentSkill] = Field(default_factory=list)
    icon_url: str | None = Field(default=None, alias="iconUrl")

    @property
    def url(self) -> str:
        """Convenience: primary interface URL."""
        return self.supported_interfaces[0].url if self.supported_interfaces else ""


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


def text_part(text: str, **kwargs: Any) -> Part:
    return Part(text=text, **kwargs)


def data_part(payload: Any, media_type: str = "application/json", **kwargs: Any) -> Part:
    return Part(data=payload, media_type=media_type, **kwargs)


def new_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    skills: list[AgentSkill],
    version: str = "0.1.0",
    streaming: bool = True,
    organization: str = "agentic",
    provider_url: str = "https://github.com/agentic",
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version=version,
        provider=AgentProvider(url=provider_url, organization=organization),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version=A2A_PROTOCOL_VERSION)],
        capabilities=AgentCapabilities(streaming=streaming, push_notifications=False),
        skills=skills,
    )
