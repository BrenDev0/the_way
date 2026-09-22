from typing import Any

from src.conversations.domain import (
    Conversation,
    ConversationCreate,
    ConversationStatus,
    TurnState,
)
from src.core.llm.domain import Message, TokenUsage, ToolCall
from src.core.tools.domain import ToolResult

from .models import ConversationRow, MessageRow


def row_to_domain(row: ConversationRow) -> Conversation:
    return Conversation(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        title=row.title,
        turn=TurnState(
            status=ConversationStatus(row.status),
            pending_tool_calls=tuple(_to_tool_call(c) for c in row.pending_tool_calls or ()),
            completed_tool_results=tuple(
                _to_tool_result(r) for r in row.completed_tool_results or ()
            ),
            iterations_used=row.iterations_used,
            usage=TokenUsage(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.total_tokens,
            ),
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(conversation: ConversationCreate) -> ConversationRow:
    return ConversationRow(
        organization_id=conversation.organization_id,
        user_id=conversation.user_id,
        title=conversation.title,
        status=ConversationStatus.IDLE,
        pending_tool_calls=[],
        completed_tool_results=[],
        iterations_used=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )


def apply_turn_state(row: ConversationRow, turn: TurnState) -> None:
    row.status = turn.status
    row.pending_tool_calls = [_from_tool_call(c) for c in turn.pending_tool_calls]
    row.completed_tool_results = [_from_tool_result(r) for r in turn.completed_tool_results]
    row.iterations_used = turn.iterations_used
    row.input_tokens = turn.usage.input_tokens
    row.output_tokens = turn.usage.output_tokens
    row.total_tokens = turn.usage.total_tokens


def message_row_to_domain(row: MessageRow) -> Message:
    message: Message = {"role": row.role, "content": row.content}
    if row.tool_calls:
        message["tool_calls"] = row.tool_calls
    if row.tool_call_id:
        message["tool_call_id"] = row.tool_call_id
    return message


def message_to_row(conversation_id: Any, position: int, message: Message) -> MessageRow:
    return MessageRow(
        conversation_id=conversation_id,
        position=position,
        role=message["role"],
        content=message.get("content", ""),
        tool_calls=message.get("tool_calls"),
        tool_call_id=message.get("tool_call_id"),
    )


def _from_tool_call(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "args": call.args}


def _to_tool_call(data: dict[str, Any]) -> ToolCall:
    return ToolCall(id=data["id"], name=data["name"], args=data["args"])


def _from_tool_result(result: ToolResult) -> dict[str, Any]:
    return {
        "tool_call_id": result.tool_call_id,
        "content": result.content,
        "failed": result.failed,
    }


def _to_tool_result(data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=data["tool_call_id"],
        content=data["content"],
        failed=data.get("failed", False),
    )
