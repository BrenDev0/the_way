import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from src.core.llm import domain as llm_domain
from src.core.llm.domain import LLMUnavailable, Message
from src.core.llm.ports import LLM
from src.core.tools.domain import (
    ClientActionRequired,
    ClientRequest,
    Decision,
    ToolResult,
)
from src.core.tools.ports import ToolExecutor

from .domain import (
    DEFAULT_MAX_CONVERSATION_CHARS,
    DEFAULT_MAX_ITERATIONS,
    LoopResult,
    LoopState,
    LoopStatus,
)

# What one picture weighs against the conversation budget: a model reads an image of the
# largest size we send as roughly 1 600 tokens, about the length of this much text.
IMAGE_CHARS = 6_400


class LoopObserver(Protocol):
    """Watches a turn as it happens: reply text as the model writes it, and every message
    the turn adds. Purely for telling someone -- nothing it does changes the turn."""

    async def on_text(self, text: str) -> None: ...

    async def on_message(self, message: Message) -> None: ...


# Called with the state just before each model call that follows new work -- tool results
# the model has not seen yet -- so it can be stored. A turn that dies at that call (the
# worker is killed, the model is unreachable) then loses only the call, never the tools
# already run.
Checkpoint = Callable[[LoopState], Awaitable[None]]

# Whether the user has asked for the work to stop. Looked at between steps, and while a reply is
# being written (at most every STOP_POLL_SECONDS), so a stop lands within a moment of being asked
# -- never in the middle of a tool.
StopCheck = Callable[[], Awaitable[bool]]
STOP_POLL_SECONDS = 0.4

# What the model is told of a call that was never run because the work was stopped first.
NOT_RUN = "Not run: the user stopped the work before this call could run."
# Ends a reply that was cut off while it was being written.
CUT_OFF = " [...]"


class StopRequested(Exception):  # noqa: N818 -- a signal, not an error
    """Raised inside the text callback to end a reply the user no longer wants."""


def conversation_size(state: LoopState) -> int:
    # A picture's base64 is not text the model reads: counted as text, one screenshot would
    # look like most of the budget. It is counted at about what it costs in tokens instead.
    total = 0
    for message in state.messages:
        content = message.get("content", "")
        total += len(llm_domain.text_of(content))
        if isinstance(content, list):
            total += IMAGE_CHARS * sum(
                1 for block in content if isinstance(block, dict) and block.get("type") == "image"
            )
    return total


async def advance(
    state: LoopState,
    llm: LLM,
    executor: ToolExecutor,
    decisions: dict[str, Decision] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
    observer: LoopObserver | None = None,
    checkpoint: Checkpoint | None = None,
    should_stop: StopCheck | None = None,
) -> LoopResult:
    messages = list(state.messages)
    saved = len(messages)
    pending = state.pending_tool_calls
    completed = state.completed_tool_results
    requests: tuple[ClientRequest, ...] = state.pending_requests
    iterations = state.iterations_used
    usage = state.usage

    def snapshot(**changes) -> LoopState:
        return LoopState(
            messages=list(messages),
            pending_tool_calls=pending,
            completed_tool_results=completed,
            iterations_used=iterations,
            usage=usage,
            pending_requests=requests,
            **changes,
        )

    async def append(*added: Message) -> None:
        messages.extend(added)
        if observer is not None:
            for message in added:
                await observer.on_message(message)

    while iterations < max_iterations:
        # Calls waiting here have been answered by the user and, for the desktop's, already
        # run on their machine: they are settled first, and the stop lands right after.
        if not pending and should_stop is not None and await should_stop():
            return LoopResult(status=LoopStatus.STOPPED, state=snapshot())

        if pending:
            try:
                results = await executor.execute(pending, decisions)
            except ClientActionRequired as exc:
                requests = exc.requests
                return LoopResult(status=LoopStatus.AWAITING_CLIENT, state=snapshot())

            await append(*_result_messages(completed + results))
            pending = ()
            completed = ()
            requests = ()
            decisions = None
            continue

        if conversation_size(snapshot()) > max_conversation_chars:
            return LoopResult(status=LoopStatus.CONVERSATION_LIMIT, state=snapshot())

        if checkpoint is not None and len(messages) > saved:
            await checkpoint(snapshot())
            saved = len(messages)

        written: list[str] = []
        checked = time.monotonic()

        async def listen(text: str) -> None:
            nonlocal checked
            written.append(text)
            if observer is not None:
                await observer.on_text(text)
            if should_stop is not None and time.monotonic() - checked >= STOP_POLL_SECONDS:
                checked = time.monotonic()
                if await should_stop():
                    raise StopRequested

        try:
            if observer is not None or should_stop is not None:
                completion = await llm.respond(messages, executor.schemas, on_text=listen)
            else:
                completion = await llm.respond(messages, executor.schemas)
        except StopRequested:
            # what was already written is part of what happened; kept, marked as cut short
            partial = "".join(written).strip()
            if partial:
                await append(llm_domain.assistant(partial + CUT_OFF))
            return LoopResult(status=LoopStatus.STOPPED, state=snapshot())
        except LLMUnavailable as exc:
            return LoopResult(status=LoopStatus.PAUSED, state=snapshot(), unavailable=exc)
        iterations += 1
        usage = usage + completion.usage
        await append(completion.message)

        if not completion.tool_calls:
            return LoopResult(
                status=LoopStatus.COMPLETED,
                state=snapshot(),
                text=completion.text,
            )

        gated = tuple(call for call in completion.tool_calls if executor.needs_client(call))
        ungated = tuple(
            call for call in completion.tool_calls if not executor.needs_client(call)
        )

        if not gated:
            await append(*_result_messages(await executor.execute(ungated)))
            continue

        ungated_results = await executor.execute(ungated) if ungated else ()
        try:
            results = await executor.execute(gated, decisions)
        except ClientActionRequired as exc:
            pending = gated
            completed = ungated_results
            requests = exc.requests
            return LoopResult(status=LoopStatus.AWAITING_CLIENT, state=snapshot())

        await append(*_result_messages(ungated_results + results))

    return LoopResult(status=LoopStatus.ITERATION_LIMIT, state=snapshot())


def result_messages(results: tuple[ToolResult, ...]) -> list[Message]:
    """The messages that answer a set of tool calls, in the order the model made them."""
    return _result_messages(results)


def _result_messages(results: tuple[ToolResult, ...]) -> list[Message]:
    return [
        llm_domain.tool_result(
            result.tool_call_id, result.content, [(image.base64, image.mime_type) for image in result.images]
        )
        for result in results
    ]
