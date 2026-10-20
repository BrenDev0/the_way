from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.background.use_cases import AUTOMATIC, TASK_NOTICE, TASK_RELAYED
from src.conversations import config, prompt
from src.conversations.domain import (
    ConversationStatus,
    PauseReason,
    TurnPause,
    TurnState,
)
from src.conversations.ports import (
    AppendMessagesFn,
    BuildContextFn,
    CommitFn,
    DrainNoticesFn,
    ExpandFn,
    GetConversationByIdFn,
    ListMessagesFn,
    SaveTurnStateFn,
)
from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import LoopObserver, advance
from src.core.llm import domain as llm_domain
from src.core.llm.domain import LLMUnavailable, Message
from src.core.llm.ports import LLM
from src.core.tools.ports import ToolExecutor

STATUS_AFTER = {
    LoopStatus.COMPLETED: ConversationStatus.IDLE,
    LoopStatus.AWAITING_CLIENT: ConversationStatus.AWAITING_CLIENT,
    LoopStatus.ITERATION_LIMIT: ConversationStatus.FAILED,
    LoopStatus.CONVERSATION_LIMIT: ConversationStatus.FAILED,
    LoopStatus.PAUSED: ConversationStatus.PAUSED,
}


def paused(reason: PauseReason, detail: str = "", retry_after_seconds: float | None = None) -> TurnPause:
    now = datetime.now(UTC)
    return TurnPause(
        reason=reason,
        detail=detail,
        paused_at=now,
        retry_after=now + timedelta(seconds=retry_after_seconds) if retry_after_seconds else None,
    )


def _pause_for(exc: LLMUnavailable) -> TurnPause:
    return paused(PauseReason(exc.reason), exc.detail, exc.retry_after)


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
    commit_fn: CommitFn | None = None,
    expand_fn: ExpandFn | None = None,
) -> ConversationStatus | None:
    """Runs the turn until it ends, waits on the client, or pauses. Along the way, before
    each model call that follows tool work, what the turn has done is stored (and with
    commit_fn, committed): a turn cut short loses at most the call it was on."""
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
    # Attachments go to the model opened up -- the picture, the PDF's text -- while the
    # stored thread keeps only references; this copy is never written back.
    opening.extend(await expand_fn(history) if expand_fn is not None else history)

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

    # how much of the loop's messages is in the database: the opening came from it, but
    # for `kept`, which goes in with the first batch stored
    stored = len(opening)

    async def store(state: LoopState) -> None:
        nonlocal stored, kept
        await append_messages_fn(conversation_id, [*kept, *state.messages[stored:]])
        kept = []
        stored = len(state.messages)

    async def checkpoint(state: LoopState) -> None:
        # Nothing is pending at a checkpoint: the calls have run and their results are in
        # the messages. Stored as such, a turn resumed from here runs none of them again.
        await store(state)
        await save_turn_state_fn(
            conversation_id,
            TurnState(
                status=ConversationStatus.RUNNING,
                iterations_used=state.iterations_used,
                usage=state.usage,
            ),
        )
        if commit_fn is not None:
            await commit_fn()

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
        checkpoint=checkpoint,
    )

    await store(result.state)
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
            pause=_pause_for(result.unavailable) if result.unavailable is not None else None,
        ),
    )
    return status


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
