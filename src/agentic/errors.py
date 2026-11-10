"""Exception hierarchy for agentic.

A2A-specific errors carry the numeric JSON-RPC codes mandated by the A2A
specification section 5.4 so that transports can surface them verbatim.
"""

from __future__ import annotations


class AgenticError(Exception):
    """Base class for every error raised by agentic."""


class ConfigError(AgenticError):
    """Invalid or missing configuration."""


class ContractError(AgenticError):
    """An artifact failed JSON Schema validation."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class LLMError(AgenticError):
    """The language model could not be reached or returned garbage."""


class ToolError(AgenticError):
    """An MCP tool call failed."""


class StageError(AgenticError):
    """A pipeline stage failed in a way that is not retryable."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


# ---------------------------------------------------------------------------
# A2A protocol errors (spec section 3.3.2 / 5.4)
# ---------------------------------------------------------------------------


class A2AError(AgenticError):
    """An A2A protocol error with a canonical JSON-RPC code and HTTP status."""

    code: int = -32603
    http_status: int = 500
    error_name: str = "InternalError"

    def __init__(self, message: str | None = None, data: object | None = None) -> None:
        super().__init__(message or self.error_name)
        self.message = message or self.error_name
        self.data = data

    def to_jsonrpc(self) -> dict[str, object]:
        err: dict[str, object] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


class TaskNotFoundError(A2AError):
    code = -32001
    http_status = 404
    error_name = "TaskNotFoundError"


class TaskNotCancelableError(A2AError):
    code = -32002
    http_status = 400
    error_name = "TaskNotCancelableError"


class PushNotificationNotSupportedError(A2AError):
    code = -32003
    http_status = 400
    error_name = "PushNotificationNotSupportedError"


class UnsupportedOperationError(A2AError):
    code = -32004
    http_status = 400
    error_name = "UnsupportedOperationError"


class ContentTypeNotSupportedError(A2AError):
    code = -32005
    http_status = 400
    error_name = "ContentTypeNotSupportedError"


class InvalidAgentResponseError(A2AError):
    code = -32006
    http_status = 500
    error_name = "InvalidAgentResponseError"


class ExtendedAgentCardNotConfiguredError(A2AError):
    code = -32007
    http_status = 400
    error_name = "ExtendedAgentCardNotConfiguredError"


class ExtensionSupportRequiredError(A2AError):
    code = -32008
    http_status = 400
    error_name = "ExtensionSupportRequiredError"


class VersionNotSupportedError(A2AError):
    code = -32009
    http_status = 400
    error_name = "VersionNotSupportedError"


class MethodNotFoundError(A2AError):
    code = -32601
    http_status = 404
    error_name = "MethodNotFoundError"


class InvalidParamsError(A2AError):
    code = -32602
    http_status = 400
    error_name = "InvalidParamsError"


A2A_ERROR_BY_NAME: dict[str, type[A2AError]] = {
    cls.error_name: cls
    for cls in (
        TaskNotFoundError,
        TaskNotCancelableError,
        PushNotificationNotSupportedError,
        UnsupportedOperationError,
        ContentTypeNotSupportedError,
        InvalidAgentResponseError,
        ExtendedAgentCardNotConfiguredError,
        ExtensionSupportRequiredError,
        VersionNotSupportedError,
        MethodNotFoundError,
        InvalidParamsError,
    )
}
