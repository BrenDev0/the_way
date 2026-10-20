from collections.abc import Sequence
from uuid import UUID

from src.conversations import attachments as attachments_module
from src.conversations.domain import (
    Conversation,
    ConversationStatus,
    ToolResolution,
    TurnState,
)
from src.conversations.ports import (
    AppendMessagesFn,
    GetConversationForUserFn,
    SaveTurnStateFn,
)
from src.core.exceptions import ConflictError, ValidationError
from src.core.tools.domain import Decision, ToolLocation

from .common import not_found

# A new message may follow a paused turn: what it did is kept in the history, and the
# user chose to move on rather than retry it.
ACCEPTS_MESSAGES = frozenset({ConversationStatus.IDLE, ConversationStatus.PAUSED})


async def send_message(
    conversation_id: UUID,
    user_id: UUID,
    message: str,
    get_conversation_for_user_fn: GetConversationForUserFn,
    append_messages_fn: AppendMessagesFn,
    save_turn_state_fn: SaveTurnStateFn,
    attachments: Sequence[dict] = (),
) -> Conversation:
    """`attachments`: references to files the user attached (attachments.py), already
    checked to be theirs."""
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise not_found()

    if not message.strip() and not attachments:
        raise ValidationError(message="Write a message or attach a file", code="message_empty")

    if conversation.turn.status not in ACCEPTS_MESSAGES:
        raise ConflictError(
            message="This conversation is still working on the previous message",
            code="conversation_busy",
        )

    await append_messages_fn(conversation_id, [attachments_module.user_message(message, attachments)])
    started = TurnState(status=ConversationStatus.RUNNING, usage=conversation.turn.usage)
    return await save_turn_state_fn(conversation_id, started) or conversation


async def resume_turn(
    conversation_id: UUID,
    user_id: UUID,
    get_conversation_for_user_fn: GetConversationForUserFn,
    save_turn_state_fn: SaveTurnStateFn,
) -> Conversation:
    """Sets a paused turn running again, from where it stopped: its messages are all
    stored, so the next model call picks up after the last thing it did."""
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise not_found()

    turn = conversation.turn
    if turn.status is not ConversationStatus.PAUSED:
        raise ConflictError(
            message="This conversation has no paused turn to resume",
            code="conversation_not_paused",
        )

    resumed = TurnState(
        status=ConversationStatus.RUNNING,
        pending_tool_calls=turn.pending_tool_calls,
        completed_tool_results=turn.completed_tool_results,
        iterations_used=turn.iterations_used,
        usage=turn.usage,
        pending_requests=turn.pending_requests,
        decisions=turn.decisions,
    )
    return await save_turn_state_fn(conversation_id, resumed) or conversation


async def resolve_tool_calls(
    conversation_id: UUID,
    user_id: UUID,
    resolutions: Sequence[ToolResolution],
    get_conversation_for_user_fn: GetConversationForUserFn,
    save_turn_state_fn: SaveTurnStateFn,
) -> Conversation:
    """Record the client's answer to every call the turn is paused on, and set it running
    again. All of them at once: a partial answer would resume a turn that immediately
    pauses on the rest, for a round trip that achieves nothing."""
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise not_found()

    turn = conversation.turn
    if turn.status is not ConversationStatus.AWAITING_CLIENT:
        raise ConflictError(
            message="This conversation is not waiting on any tool calls",
            code="conversation_not_awaiting_client",
        )

    locations = {request.call.id: request.location for request in turn.pending_requests}
    pending = [call.id for call in turn.pending_tool_calls]
    decisions: dict[str, Decision] = {}

    for resolution in resolutions:
        call_id = resolution.tool_call_id
        if call_id not in pending:
            raise ValidationError(
                message=f"'{call_id}' is not one of the tool calls this conversation is waiting on",
                code="tool_call_not_pending",
            )
        if call_id in decisions:
            raise ValidationError(
                message=f"'{call_id}' was resolved more than once",
                code="tool_call_resolved_twice",
            )

        on_desktop = locations.get(call_id) is ToolLocation.DESKTOP
        if resolution.approved and on_desktop and resolution.output is None:
            raise ValidationError(
                message=f"'{call_id}' runs on the desktop, so approving it needs its output",
                code="tool_call_output_required",
            )
        if resolution.output is not None and not on_desktop:
            raise ValidationError(
                message=f"'{call_id}' runs on the server; send only whether it is approved",
                code="tool_call_output_not_expected",
            )

        decisions[call_id] = Decision(
            approved=resolution.approved,
            feedback=resolution.feedback,
            output=resolution.output,
            failed=resolution.failed,
            args=resolution.args,
        )

    missing = [call_id for call_id in pending if call_id not in decisions]
    if missing:
        raise ValidationError(
            message=(
                "Every pending tool call must be resolved together; missing: "
                f"{', '.join(missing)}"
            ),
            code="tool_calls_unresolved",
        )

    resumed = TurnState(
        status=ConversationStatus.RUNNING,
        pending_tool_calls=turn.pending_tool_calls,
        completed_tool_results=turn.completed_tool_results,
        iterations_used=turn.iterations_used,
        usage=turn.usage,
        pending_requests=turn.pending_requests,
        decisions=decisions,
    )
    return await save_turn_state_fn(conversation_id, resumed) or conversation
