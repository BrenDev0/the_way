from collections.abc import Sequence
from uuid import UUID

from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import advance
from src.core.exceptions import ConflictError, NotFoundError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import Completion, Message
from src.core.llm.ports import LLM
from src.core.tools.ports import ToolExecutor

from . import config, prompt
from .domain import Conversation, ConversationCreate, ConversationStatus, TurnState
from .ports import (
    AppendMessagesFn,
    BuildKnowledgeContextFn,
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationByIdFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesFn,
    ListMessagesForUserFn,
    SaveTurnStateFn,
)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Conversation not found", code="conversation_not_found")


def build_messages(message: str, history: Sequence[Message] = ()) -> list[Message]:
    return [llm_domain.system(prompt.SYSTEM), *history, llm_domain.user(message)]


async def reply(message: str, llm: LLM, history: Sequence[Message] = ()) -> Completion:
    return await llm.respond(build_messages(message, history))


async def start_conversation(
    organization_id: UUID,
    user_id: UUID,
    title: str,
    create_conversation_fn: CreateConversationFn,
) -> Conversation:
    return await create_conversation_fn(
        ConversationCreate(organization_id=organization_id, user_id=user_id, title=title)
    )


async def get_conversation(
    conversation_id: UUID,
    user_id: UUID,
    get_conversation_for_user_fn: GetConversationForUserFn,
) -> Conversation:
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise _not_found()
    return conversation


async def list_conversations(
    user_id: UUID,
    list_conversations_for_user_fn: ListConversationsForUserFn,
) -> Sequence[Conversation]:
    return await list_conversations_for_user_fn(user_id)


async def read_messages(
    conversation_id: UUID,
    user_id: UUID,
    list_messages_for_user_fn: ListMessagesForUserFn,
) -> list[Message]:
    messages = await list_messages_for_user_fn(conversation_id, user_id)
    if messages is None:
        raise _not_found()
    return messages


async def delete_conversation(
    conversation_id: UUID,
    user_id: UUID,
    delete_conversation_for_user_fn: DeleteConversationForUserFn,
) -> None:
    if not await delete_conversation_for_user_fn(conversation_id, user_id):
        raise _not_found()


STATUS_AFTER = {
    LoopStatus.COMPLETED: ConversationStatus.IDLE,
    LoopStatus.AWAITING_APPROVAL: ConversationStatus.AWAITING_APPROVAL,
    LoopStatus.ITERATION_LIMIT: ConversationStatus.FAILED,
    LoopStatus.CONVERSATION_LIMIT: ConversationStatus.FAILED,
}


async def send_message(
    conversation_id: UUID,
    user_id: UUID,
    message: str,
    get_conversation_for_user_fn: GetConversationForUserFn,
    append_messages_fn: AppendMessagesFn,
    save_turn_state_fn: SaveTurnStateFn,
) -> Conversation:
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise _not_found()

    if conversation.turn.status is not ConversationStatus.IDLE:
        raise ConflictError(
            message="This conversation is still working on the previous message",
            code="conversation_busy",
        )

    await append_messages_fn(conversation_id, [llm_domain.user(message)])
    started = TurnState(status=ConversationStatus.RUNNING, usage=conversation.turn.usage)
    return await save_turn_state_fn(conversation_id, started) or conversation


async def advance_turn(
    conversation_id: UUID,
    llm: LLM,
    executor: ToolExecutor,
    get_conversation_by_id_fn: GetConversationByIdFn,
    list_messages_fn: ListMessagesFn,
    append_messages_fn: AppendMessagesFn,
    save_turn_state_fn: SaveTurnStateFn,
    build_knowledge_context_fn: BuildKnowledgeContextFn | None = None,
    max_iterations: int = config.MAX_ITERATIONS,
) -> ConversationStatus | None:
    conversation = await get_conversation_by_id_fn(conversation_id)
    if conversation is None or conversation.turn.status is not ConversationStatus.RUNNING:
        return None

    history = await list_messages_fn(conversation_id)

    opening = [llm_domain.system(prompt.SYSTEM)]
    if build_knowledge_context_fn is not None:
        knowledge = await build_knowledge_context_fn(conversation.organization_id)
        if knowledge:
            opening.append(llm_domain.system(knowledge))
    opening.extend(history)

    result = await advance(
        LoopState(
            messages=opening,
            pending_tool_calls=conversation.turn.pending_tool_calls,
            completed_tool_results=conversation.turn.completed_tool_results,
            iterations_used=conversation.turn.iterations_used,
            usage=conversation.turn.usage,
        ),
        llm,
        executor,
        max_iterations=max_iterations,
    )

    await append_messages_fn(conversation_id, result.state.messages[len(opening) :])
    status = STATUS_AFTER[result.status]
    await save_turn_state_fn(
        conversation_id,
        TurnState(
            status=status,
            pending_tool_calls=result.state.pending_tool_calls,
            completed_tool_results=result.state.completed_tool_results,
            iterations_used=result.state.iterations_used,
            usage=result.state.usage,
        ),
    )
    return status
