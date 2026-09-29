from collections.abc import Sequence
from dataclasses import dataclass, field

from src.core.llm import domain as llm_domain
from src.core.llm.domain import Message, TokenUsage
from src.core.llm.ports import LLM
from src.core.tools.ports import ToolExecutor

from .domain import DEFAULT_MAX_ITERATIONS, LoopState, LoopStatus
from .loop import advance

WRAP_UP = (
    "You have reached the limit on tool calls for this run and cannot make another. "
    "Reply now in plain text: say what you actually completed, name any file or record "
    "you changed, and state plainly what is still unfinished. Claim nothing you did not "
    "verify."
)

NO_ACCOUNT = (
    "The run stopped after {steps} steps before finishing, and gave no account of where "
    "it got to. Nothing it produced is guaranteed complete."
)


@dataclass(frozen=True)
class AssistantRun:
    """What a sub-assistant produced. `finished` is False when the step budget ran out,
    in which case `text` is the assistant's own account of where it got to -- the one
    thing needed to decide whether to retry it or rewrite the instructions."""

    text: str
    finished: bool
    usage: TokenUsage = field(default_factory=TokenUsage)


async def run_assistant(
    llm: LLM,
    executor: ToolExecutor,
    messages: Sequence[Message],
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AssistantRun:
    """Run one assistant to completion with nobody watching. The executor's gate decides
    what happens to gated calls; a sub-assistant is never handed a suspending one."""
    result = await advance(
        LoopState(messages=list(messages)), llm, executor, max_iterations=max_iterations
    )

    if result.status is LoopStatus.COMPLETED:
        return AssistantRun(text=result.text, finished=True, usage=result.state.usage)

    account = await _wrap_up(llm, executor, result.state.messages)
    return AssistantRun(
        text=account or NO_ACCOUNT.format(steps=result.state.iterations_used),
        finished=False,
        usage=result.state.usage,
    )


async def _wrap_up(llm: LLM, executor: ToolExecutor, messages: list[Message]) -> str:
    # The tools stay bound: a history holding tool calls is refused by some providers
    # when no tools are declared. A reply that calls one anyway is simply discarded.
    try:
        completion = await llm.respond(
            [*messages, llm_domain.system(WRAP_UP)], executor.schemas
        )
    except Exception:  # noqa: BLE001
        return ""
    return "" if completion.tool_calls else completion.text
