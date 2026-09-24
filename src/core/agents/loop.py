from src.core.llm import domain as llm_domain
from src.core.llm.ports import LLM
from src.core.tools.domain import ApprovalRequired, Decision, ToolResult
from src.core.tools.ports import ToolExecutor

from .domain import (
    DEFAULT_MAX_CONVERSATION_CHARS,
    DEFAULT_MAX_ITERATIONS,
    LoopResult,
    LoopState,
    LoopStatus,
)


def conversation_size(state: LoopState) -> int:
    return sum(len(str(message.get("content", ""))) for message in state.messages)


async def advance(
    state: LoopState,
    llm: LLM,
    executor: ToolExecutor,
    decisions: dict[str, Decision] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
) -> LoopResult:
    messages = list(state.messages)
    pending = state.pending_tool_calls
    completed = state.completed_tool_results
    iterations = state.iterations_used
    usage = state.usage

    def snapshot(**changes) -> LoopState:
        return LoopState(
            messages=list(messages),
            pending_tool_calls=pending,
            completed_tool_results=completed,
            iterations_used=iterations,
            usage=usage,
            **changes,
        )

    while iterations < max_iterations:
        if pending:
            try:
                results = await executor.execute(pending, decisions)
            except ApprovalRequired:
                return LoopResult(status=LoopStatus.AWAITING_APPROVAL, state=snapshot())

            messages.extend(_result_messages(completed + results))
            pending = ()
            completed = ()
            decisions = None
            continue

        if conversation_size(snapshot()) > max_conversation_chars:
            return LoopResult(status=LoopStatus.CONVERSATION_LIMIT, state=snapshot())

        completion = await llm.respond(messages, executor.schemas)
        iterations += 1
        usage = usage + completion.usage
        messages.append(completion.message)

        if not completion.tool_calls:
            return LoopResult(
                status=LoopStatus.COMPLETED,
                state=snapshot(),
                text=completion.text,
            )

        gated = tuple(call for call in completion.tool_calls if executor.requires_approval(call))
        ungated = tuple(
            call for call in completion.tool_calls if not executor.requires_approval(call)
        )

        if not gated:
            messages.extend(_result_messages(await executor.execute(ungated)))
            continue

        ungated_results = await executor.execute(ungated) if ungated else ()
        try:
            results = await executor.execute(gated, decisions)
        except ApprovalRequired:
            pending = gated
            completed = ungated_results
            return LoopResult(status=LoopStatus.AWAITING_APPROVAL, state=snapshot())

        messages.extend(_result_messages(ungated_results + results))

    return LoopResult(status=LoopStatus.ITERATION_LIMIT, state=snapshot())


def _result_messages(results: tuple[ToolResult, ...]) -> list:
    return [llm_domain.tool_result(result.tool_call_id, result.content) for result in results]
