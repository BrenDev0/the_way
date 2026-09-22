from dataclasses import dataclass, field
from typing import Any

Message = dict[str, Any]


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

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
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
