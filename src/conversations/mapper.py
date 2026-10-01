from src.core.llm.domain import Message
from src.core.tools.domain import ClientRequest

from .domain import Conversation, ToolResolution
from .schemas import (
    ConversationResponse,
    MessageResponse,
    PendingToolCallResponse,
    ToolResolutionRequest,
)


def domain_to_conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        client=conversation.client,
        status=conversation.turn.status,
        pending_tool_calls=[
            request_to_response(request) for request in conversation.turn.pending_requests
        ],
        iterations_used=conversation.turn.iterations_used,
        total_tokens=conversation.turn.usage.total_tokens,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def request_to_response(request: ClientRequest) -> PendingToolCallResponse:
    return PendingToolCallResponse(
        id=request.call.id,
        name=request.call.name,
        args=request.call.args,
        location=request.location,
        requires_approval=request.requires_approval,
        detail=request.detail,
        choices={name: list(values) for name, values in request.choices.items()},
        preview=request.preview if isinstance(request.preview, str) else None,
        always_ask=request.always_ask,
    )


def resolution_request_to_domain(request: ToolResolutionRequest) -> ToolResolution:
    return ToolResolution(
        tool_call_id=request.tool_call_id,
        approved=request.approved,
        feedback=request.feedback,
        output=request.output,
        failed=request.failed,
        args=dict(request.args),
    )


def message_to_response(message: Message) -> MessageResponse:
    return MessageResponse(
        role=message["role"],
        content=message.get("content", ""),
        tool_calls=message.get("tool_calls"),
        tool_call_id=message.get("tool_call_id"),
    )
