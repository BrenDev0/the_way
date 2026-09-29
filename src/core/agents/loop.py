from typing import Protocol

from src.core.llm import domain as llm_domain
from src.core.llm.domain import Message
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


class LoopObserver(Protocol):
    """Watches a turn as it happens: reply text as the model writes it, and every message
    the turn adds. Purely for telling someone -- nothing it does changes the turn."""

    async def on_text(self, text: str) -> None: ...

    async def on_message(self, message: Message) -> None: ...


def conversation_size(state: LoopState) -> int:
    return sum(len(str(message.get("content", ""))) for message in state.messages)


async def advance(
    state: LoopState,
    llm: LLM,
    executor: ToolExecutor,
    decisions: dict[str, Decision] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
    observer: LoopObserver | None = None,
) -> LoopResult:
    messages = list(state.messages)
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

        if observer is not None:
            completion = await llm.respond(messages, executor.schemas, on_text=observer.on_text)
        else:
            completion = await llm.respond(messages, executor.schemas)
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


def _result_messages(results: tuple[ToolResult, ...]) -> list[Message]:
    return [llm_domain.tool_result(result.tool_call_id, result.content) for result in results]
