from collections.abc import Sequence
from uuid import UUID

from src.background.use_cases import AUTOMATIC, TASK_NOTICE, TASK_RELAYED
from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import LoopObserver, advance
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import Completion, Message
from src.core.llm.ports import LLM
from src.core.tools.domain import Decision, ToolLocation
from src.core.tools.ports import ToolExecutor

from . import config, prompt
from .domain import (
    Conversation,
    ConversationClient,
    ConversationCreate,
    ConversationStatus,
    ToolResolution,
    TurnState,
)
from .ports import (
    AppendMessagesFn,
    BuildContextFn,
    CreateConversationFn,
    DeleteConversationForUserFn,
    DrainNoticesFn,
    GetConversationByIdFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesFn,
    ListMessagesForUserFn,
    RenameConversationFn,
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
    client: ConversationClient = ConversationClient.DESKTOP,
) -> Conversation:
    return await create_conversation_fn(
        ConversationCreate(
            organization_id=organization_id, user_id=user_id, title=title, client=client
        )
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
    LoopStatus.AWAITING_CLIENT: ConversationStatus.AWAITING_CLIENT,
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
    build_context_fn: BuildContextFn | None = None,
    max_iterations: int = config.MAX_ITERATIONS,
    drain_notices_fn: DrainNoticesFn | None = None,
    observer: LoopObserver | None = None,
) -> ConversationStatus | None:
    conversation = await get_conversation_by_id_fn(conversation_id)
    if conversation is None or conversation.turn.status is not ConversationStatus.RUNNING:
        return None

    history = await list_messages_fn(conversation_id)
    context = await build_context_fn(conversation) if build_context_fn is not None else None

    # Static first, volatile last: a provider caches the prompt up to the first byte that
    # differs from the last request, so what changes between turns must not sit ahead of
    # the history -- there it would re-bill the whole conversation each time it changed.
    opening = [llm_domain.system(prompt.SYSTEM)]
    if context is not None:
        opening += [llm_domain.system(block) for block in context.stable if block]
    opening.extend(history)

    # A background task that finished since the last turn is relayed in this reply. Only
    # the relayed form is kept -- left as a live notice it would be announced every turn.
    kept: list[Message] = []
    news = await drain_notices_fn(conversation) if drain_notices_fn is not None else ""
    if news:
        notice = TASK_NOTICE.format(news=news)
        # A turn the server started itself to report a finished task has no new user
        # message: the history ends on the assistant's last reply, which some providers
        # refuse to continue. The notice is put as the turn's opening line instead -- not
        # kept, so the user never sees words they did not write.
        relaying = not history or history[-1].get("role") == "assistant"
        opening.append(llm_domain.user(f"{AUTOMATIC}\n\n{notice}") if relaying else llm_domain.system(notice))
        kept.append(llm_domain.system(TASK_RELAYED.format(news=news)))

    # The date, the folder, voice... come after the history, and are kept in it: what is
    # sent stays the stored conversation plus what is new, which the next request finds
    # unchanged. Said again only when it changed, so an unchanged day adds nothing.
    if context is not None and context.current and _says_anew(history, context.current):
        current = llm_domain.system(context.current)
        opening.append(current)
        kept.append(current)

    result = await advance(
        LoopState(
            messages=opening,
            pending_tool_calls=conversation.turn.pending_tool_calls,
            completed_tool_results=conversation.turn.completed_tool_results,
            iterations_used=conversation.turn.iterations_used,
            usage=conversation.turn.usage,
            pending_requests=conversation.turn.pending_requests,
        ),
        llm,
        executor,
        decisions=dict(conversation.turn.decisions) or None,
        max_iterations=max_iterations,
        observer=observer,
    )

    await append_messages_fn(conversation_id, [*kept, *result.state.messages[len(opening) :]])
    status = STATUS_AFTER[result.status]
    await save_turn_state_fn(
        conversation_id,
        TurnState(
            status=status,
            pending_tool_calls=result.state.pending_tool_calls,
            completed_tool_results=result.state.completed_tool_results,
            iterations_used=result.state.iterations_used,
            usage=result.state.usage,
            pending_requests=result.state.pending_requests,
        ),
    )
    return status


async def name_conversation(
    conversation: Conversation,
    history: Sequence[Message],
    llm: LLM,
    rename_fn: RenameConversationFn,
) -> Conversation | None:
    """Names a conversation after its first exchange, if it still has a placeholder title
    and has one: a user message and a reply to it. None when nothing changed."""
    if conversation.title not in config.PLACEHOLDER_TITLES:
        return None
    exchange = _first_exchange(history)
    if exchange is None:
        return None

    user_text, assistant_text = exchange
    completion = await llm.respond([
        llm_domain.system(prompt.TITLE_SYSTEM),
        llm_domain.user(
            prompt.TITLE_USER.format(
                user=user_text[: config.TITLE_EXCERPT_CHARS],
                assistant=assistant_text[: config.TITLE_EXCERPT_CHARS],
            )
        ),
    ])
    title = _clean_title(completion.text)
    if not title or title in config.PLACEHOLDER_TITLES:
        return None
    return await rename_fn(conversation.id, title)


def _text(content: object) -> str:
    """A message's words: OpenAI stores a string, Anthropic a list of typed blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) for block in content
            if isinstance(block, dict) and block.get("type") in (None, "text")
        ).strip()
    return ""


def _first_exchange(history: Sequence[Message]) -> tuple[str, str] | None:
    """The user's first message and the first reply with words in it, after it."""
    user_text = ""
    for message in history:
        role = message.get("role")
        if role == "user" and not user_text:
            user_text = _text(message.get("content"))
        elif role == "assistant" and user_text and (reply := _text(message.get("content"))):
            return user_text, reply
    return None


def _clean_title(text: str) -> str:
    title = " ".join(text.split())
    for prefix in ("Title:", "Título:"):
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix):]
    # quotes and a final period in either order -- '"Banner".' as well as '"Banner."'
    title = title.strip().rstrip(".").strip("\"'`*#« »“”").rstrip(".").strip()
    if len(title) > config.MAX_TITLE_CHARS:
        title = title[: config.MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def _says_anew(history: Sequence[Message], current: str) -> bool:
    """Whether the turn's context must be said again: it differs from the last said, and
    the history does not end on tool calls -- their results must follow them directly."""
    if history and history[-1].get("role") == "assistant" and history[-1].get("tool_calls"):
        return False
    said = next(
        (
            m.get("content")
            for m in reversed(history)
            if m.get("role") == "system" and str(m.get("content", "")).startswith(prompt.CONTEXT_HEADER)
        ),
        None,
    )
    return said != current


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
        raise _not_found()

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
