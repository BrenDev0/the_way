from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

Message = dict[str, Any]


class UnavailableReason(StrEnum):
    RATE_LIMIT = "rate_limit"
    # the account is out of credit or over its spending limit
    QUOTA = "quota"
    TIMEOUT = "timeout"
    # the provider failed or could not be reached: a 5xx, overloaded, a dropped connection
    PROVIDER_ERROR = "provider_error"
    # the key was refused: revoked, mistyped, or not allowed this model
    CREDENTIALS = "credentials"


class LLMUnavailable(Exception):
    """The provider could not answer, for a reason that passes or that the user can fix.
    Never the request's fault: the same request, sent again later, can succeed -- so the
    work that led to it is kept, not thrown away."""

    def __init__(self, reason: UnavailableReason, detail: str = "", retry_after: float | None = None) -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail
        # seconds the provider asked to wait, when it said
        self.retry_after = retry_after


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Of input_tokens, how many were read from the provider's prompt cache (billed at a
    # fraction) and how many were written to it -- the measure of whether caching works.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class Completion:
    message: Message
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)


def system(content: str) -> Message:
    return {"role": "system", "content": content}


def user(content: str) -> Message:
    return {"role": "user", "content": content}


def assistant(content: Any, tool_calls: tuple[ToolCall, ...] = ()) -> Message:
    message: Message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": call.id, "name": call.name, "args": call.args, "type": "tool_call"}
            for call in tool_calls
        ]
    return message


def tool_result(tool_call_id: str, content: str) -> Message:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}
