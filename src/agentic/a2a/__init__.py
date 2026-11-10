"""A2A protocol: canonical data model, server, client.

Implements A2A v1.0.0 over the JSON-RPC 2.0 and HTTP+JSON/REST bindings, with
SSE streaming. Wire shapes match the ProtoJSON encoding of ``spec/a2a.proto``
and are verified against the official ``a2a-sdk`` protobuf types in the test
suite (``tests/test_a2a_wire_compat.py``).
"""

from __future__ import annotations

from .client import A2AClient, AgentEndpoint
from .models import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    data_part,
    new_agent_card,
    text_part,
)
from .server import A2AHandler, A2AServer

__all__ = [
    "A2AClient",
    "A2AHandler",
    "A2AServer",
    "AgentCapabilities",
    "AgentCard",
    "AgentEndpoint",
    "AgentExtension",
    "AgentInterface",
    "AgentProvider",
    "AgentSkill",
    "Artifact",
    "Message",
    "Part",
    "Role",
    "SendMessageConfiguration",
    "SendMessageRequest",
    "StreamResponse",
    "Task",
    "TaskArtifactUpdateEvent",
    "TaskPushNotificationConfig",
    "TaskState",
    "TaskStatus",
    "TaskStatusUpdateEvent",
    "data_part",
    "new_agent_card",
    "text_part",
]
