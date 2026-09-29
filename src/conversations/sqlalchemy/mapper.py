from typing import Any

from src.conversations.domain import (
    Conversation,
    ConversationClient,
    ConversationCreate,
    ConversationStatus,
    TurnState,
)
from src.core.llm.domain import Message, TokenUsage, ToolCall
from src.core.tools.domain import ClientRequest, Decision, ToolLocation, ToolResult

from .models import ConversationRow, MessageRow


def row_to_domain(row: ConversationRow) -> Conversation:
    pending = row.pending_tool_calls or ()
    return Conversation(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        title=row.title,
        turn=TurnState(
            status=ConversationStatus(row.status),
            pending_tool_calls=tuple(_to_tool_call(c) for c in pending),
            completed_tool_results=tuple(
                _to_tool_result(r) for r in row.completed_tool_results or ()
            ),
            iterations_used=row.iterations_used,
            usage=TokenUsage(
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.total_tokens,
            ),
            pending_requests=tuple(_to_request(c) for c in pending),
            decisions={
                call_id: _to_decision(data) for call_id, data in (row.tool_decisions or {}).items()
            },
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        client=ConversationClient(row.client or ConversationClient.DESKTOP),
    )


def domain_create_to_row(conversation: ConversationCreate) -> ConversationRow:
    return ConversationRow(
        organization_id=conversation.organization_id,
        user_id=conversation.user_id,
        title=conversation.title,
        client=conversation.client,
        status=ConversationStatus.IDLE,
        pending_tool_calls=[],
        completed_tool_results=[],
        tool_decisions={},
        iterations_used=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )


def apply_turn_state(row: ConversationRow, turn: TurnState) -> None:
    requests = {request.call.id: request for request in turn.pending_requests}
    row.status = turn.status
    row.pending_tool_calls = [
        _from_tool_call(call, requests.get(call.id)) for call in turn.pending_tool_calls
    ]
    row.completed_tool_results = [_from_tool_result(r) for r in turn.completed_tool_results]
    row.tool_decisions = {
        call_id: _from_decision(decision) for call_id, decision in turn.decisions.items()
    }
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


def _from_tool_call(call: ToolCall, request: ClientRequest | None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": call.id, "name": call.name, "args": call.args}
    if request is not None:
        data["location"] = str(request.location)
        data["requires_approval"] = request.requires_approval
        data["detail"] = request.detail
    return data


def _to_tool_call(data: dict[str, Any]) -> ToolCall:
    return ToolCall(id=data["id"], name=data["name"], args=data["args"])


def _to_request(data: dict[str, Any]) -> ClientRequest:
    return ClientRequest(
        call=_to_tool_call(data),
        location=ToolLocation(data.get("location", ToolLocation.SERVER)),
        requires_approval=data.get("requires_approval", True),
        detail=data.get("detail"),
    )


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


def _from_decision(decision: Decision) -> dict[str, Any]:
    return {
        "approved": decision.approved,
        "feedback": decision.feedback,
        "output": decision.output,
        "failed": decision.failed,
    }


def _to_decision(data: dict[str, Any]) -> Decision:
    return Decision(
        approved=data["approved"],
        feedback=data.get("feedback", ""),
        output=data.get("output"),
        failed=data.get("failed", False),
    )
