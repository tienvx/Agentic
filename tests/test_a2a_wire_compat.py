"""A2A wire compatibility against the official a2a-sdk protobuf types.

These tests are the proof that ``agentic`` speaks real A2A v1.0.0 rather than a
dialect: every document we emit must parse into the reference protobuf message
and re-serialise identically, and every document the reference implementation
emits must parse into ours.
"""

from __future__ import annotations

import pytest

json_format = pytest.importorskip("google.protobuf.json_format")
from a2a.types import a2a_pb2 as pb  # noqa: E402

from agentic.a2a import models as m  # noqa: E402


def roundtrip(message: m.WireModel, proto_type: type) -> None:
    wire = message.to_wire()
    parsed = json_format.ParseDict(wire, proto_type())
    assert json_format.MessageToDict(parsed) == wire, f"wire drift for {type(message).__name__}"


def test_task_roundtrips() -> None:
    task = m.Task(
        id="t1",
        context_id="c1",
        status=m.TaskStatus(state=m.TaskState.WORKING),
        artifacts=[m.Artifact(name="Requirements", parts=[m.data_part({"project_name": "app"})])],
    )
    roundtrip(task, pb.Task)
    parsed = json_format.ParseDict(task.to_wire(), pb.Task())
    assert parsed.status.state == pb.TaskState.TASK_STATE_WORKING
    assert parsed.artifacts[0].parts[0].data.struct_value.fields["project_name"].string_value == "app"


def test_message_roundtrips() -> None:
    message = m.Message(
        role=m.Role.USER,
        parts=[m.text_part("hello"), m.data_part({"k": "v"})],
        context_id="ctx",
        task_id="task",
        reference_task_ids=["other"],
    )
    roundtrip(message, pb.Message)
    parsed = json_format.ParseDict(message.to_wire(), pb.Message())
    assert parsed.role == pb.Role.ROLE_USER
    assert parsed.parts[0].text == "hello"


def test_part_oneof_kinds() -> None:
    for part in (
        m.text_part("text"),
        m.data_part({"a": 1}),
        m.Part(url="https://example.com/f.json", media_type="application/json"),
        m.Part(raw="aGk=", filename="f.bin"),
    ):
        roundtrip(part, pb.Part)


def test_agent_card_roundtrips() -> None:
    card = m.new_agent_card(
        name="Scout",
        description="Turns ideas into briefs.",
        url="http://127.0.0.1:9000/agents/scout",
        skills=[m.AgentSkill(id="scout", name="Idea Scout", description="Briefs", tags=["discovery"])],
    )
    roundtrip(card, pb.AgentCard)
    parsed = json_format.ParseDict(card.to_wire(), pb.AgentCard())
    assert parsed.supported_interfaces[0].protocol_version == "1.0"
    assert parsed.capabilities.streaming is True


def test_send_message_request_roundtrips() -> None:
    request = m.SendMessageRequest(
        message=m.Message(role=m.Role.USER, parts=[m.text_part("build me a thing")]),
        configuration=m.SendMessageConfiguration(return_immediately=True, history_length=5),
    )
    roundtrip(request, pb.SendMessageRequest)
    parsed = json_format.ParseDict(request.to_wire(), pb.SendMessageRequest())
    assert parsed.configuration.return_immediately is True


def test_stream_response_oneof_roundtrips() -> None:
    events = [
        m.StreamResponse(task=m.Task(id="t", status=m.TaskStatus(state=m.TaskState.SUBMITTED))),
        m.StreamResponse(
            status_update=m.TaskStatusUpdateEvent(
                task_id="t", context_id="c", status=m.TaskStatus(state=m.TaskState.COMPLETED)
            )
        ),
        m.StreamResponse(
            artifact_update=m.TaskArtifactUpdateEvent(
                task_id="t",
                context_id="c",
                artifact=m.Artifact(name="Review", parts=[m.data_part({"verdict": "approve"})]),
                last_chunk=True,
            )
        ),
    ]
    for event in events:
        roundtrip(event, pb.StreamResponse)


def test_reference_proto_parses_into_our_models() -> None:
    proto_task = pb.Task(
        id="t9",
        context_id="c9",
        status=pb.TaskStatus(state=pb.TaskState.TASK_STATE_COMPLETED),
        history=[pb.Message(message_id="m1", role=pb.Role.ROLE_USER, parts=[pb.Part(text="go")])],
    )
    ours = m.Task.model_validate(json_format.MessageToDict(proto_task))
    assert ours.id == "t9"
    assert ours.status.state is m.TaskState.COMPLETED
    assert ours.history[0].parts[0].as_text() == "go"


def test_task_state_enum_names_match_spec() -> None:
    expected = {
        "TASK_STATE_UNSPECIFIED",
        "TASK_STATE_SUBMITTED",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_AUTH_REQUIRED",
    }
    assert {state.value for state in m.TaskState} == expected


def test_terminal_state_semantics() -> None:
    assert m.TaskState.COMPLETED.is_terminal
    assert m.TaskState.FAILED.is_terminal
    assert not m.TaskState.WORKING.is_terminal
    assert m.TaskState.INPUT_REQUIRED.is_interrupted


def test_wire_omits_empty_collections() -> None:
    """ProtoJSON omits defaults; emitting them would be noise to strict parsers."""
    wire = m.Task(id="t", status=m.TaskStatus(state=m.TaskState.SUBMITTED)).to_wire()
    assert "artifacts" not in wire
    assert "history" not in wire
