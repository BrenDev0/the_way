from src.core.llm.domain import Message

from .domain import Conversation
from .schemas import ConversationResponse, MessageResponse


def domain_to_conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        status=conversation.turn.status,
        iterations_used=conversation.turn.iterations_used,
        total_tokens=conversation.turn.usage.total_tokens,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def message_to_response(message: Message) -> MessageResponse:
    return MessageResponse(
        role=message["role"],
        content=message.get("content", ""),
        tool_calls=message.get("tool_calls"),
        tool_call_id=message.get("tool_call_id"),
    )
