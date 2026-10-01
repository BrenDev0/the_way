import asyncio
import inspect
from collections.abc import Mapping, Sequence
from contextvars import ContextVar

from pydantic import BaseModel

from src.core.llm.domain import ToolCall

from .domain import (
    MAX_ERROR_CHARS,
    NO_DESKTOP,
    UNKNOWN_TOOL,
    ClientRequest,
    Decision,
    Tool,
    ToolLocation,
    ToolResult,
    chosen_args,
    truncate,
)
from .ports import ApprovalGate, ToolEvents

# Every result lands in the conversation and is resent on every later step, so one
# oversized page or dataset must not be allowed to swallow the context window.
MAX_OUTPUT_CHARS = 60_000

# The id of the tool call whose handler is running. A tool that runs an assistant of its
# own (a page builder, a skill writer) hands that assistant an executor; its calls are
# started inside this one's handler, so reading this tells them which call they belong to.
_current_call: ContextVar[str | None] = ContextVar("current_tool_call", default=None)


def current_call() -> str | None:
    return _current_call.get()


class NullEvents:
    async def tool_started(self, call: ToolCall) -> None:
        return None

    async def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        return None


class Executor:
    def __init__(
        self,
        tools: Mapping[str, Tool],
        gate: ApprovalGate,
        events: ToolEvents | None = None,
        max_error_chars: int = MAX_ERROR_CHARS,
        max_output_chars: int = MAX_OUTPUT_CHARS,
    ) -> None:
        self._tools = dict(tools)
        self._gate = gate
        self._events = events or NullEvents()
        self._max_error_chars = max_error_chars
        self._max_output_chars = max_output_chars

    @property
    def schemas(self) -> tuple[type[BaseModel], ...]:
        return tuple(tool.schema for tool in self._tools.values())

    def requires_approval(self, call: ToolCall) -> bool:
        tool = self._tools.get(call.name)
        return bool(tool and tool.requires_approval)

    def needs_client(self, call: ToolCall) -> bool:
        tool = self._tools.get(call.name)
        return bool(tool and tool.needs_client)

    async def execute(
        self,
        calls: Sequence[ToolCall],
        decisions: Mapping[str, Decision] | None = None,
    ) -> tuple[ToolResult, ...]:
        decided = dict(decisions or {})
        undecided = [
            call
            for call in calls
            if self.needs_client(call) and call.id not in decided
        ]

        if undecided:
            requests = tuple(self._client_request(call) for call in undecided)
            for call, decision in zip(undecided, await self._gate.decide(requests), strict=True):
                decided[call.id] = decision

        results = await asyncio.gather(
            *(self._run(call, decided.get(call.id)) for call in calls)
        )
        return tuple(results)

    def _client_request(self, call: ToolCall) -> ClientRequest:
        tool = self._tools[call.name]
        return ClientRequest(
            call=call,
            location=tool.location,
            requires_approval=tool.requires_approval,
            preview=_build(tool.preview, call.args),
            detail=_build(tool.describe, call.args),
            choices=tool.choices,
            always_ask=tool.always_ask,
        )

    async def _run(self, call: ToolCall, decision: Decision | None) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                content=UNKNOWN_TOOL.format(name=call.name),
                failed=True,
            )

        if decision is not None and not decision.approved:
            return ToolResult(tool_call_id=call.id, content=decision.rejection_text())

        if tool.location is ToolLocation.DESKTOP:
            return self._desktop_result(tool, call, decision)

        # what the approver picked (the model, say) replaces what was asked for
        call = ToolCall(id=call.id, name=call.name, args=chosen_args(tool, call, decision))
        await self._events.tool_started(call)
        running = _current_call.set(call.id)
        try:
            result = await self._invoke(tool, call)
        finally:
            _current_call.reset(running)
        await self._events.tool_finished(call, result)
        return result

    def _desktop_result(
        self, tool: Tool, call: ToolCall, decision: Decision | None
    ) -> ToolResult:
        # An approval with no output means a gate approved a call it could not run, which
        # is what a background worker's gate does: nobody is at a desktop to run it.
        if decision is None or decision.output is None:
            return ToolResult(
                tool_call_id=call.id, content=NO_DESKTOP.format(name=tool.name), failed=True
            )
        return ToolResult(
            tool_call_id=call.id,
            content=truncate(decision.output, self._max_output_chars),
            failed=decision.failed,
        )

    async def _invoke(self, tool: Tool, call: ToolCall) -> ToolResult:
        if tool.handler is None:
            return ToolResult(
                tool_call_id=call.id, content=UNKNOWN_TOOL.format(name=call.name), failed=True
            )

        try:
            if inspect.iscoroutinefunction(tool.handler):
                output = await tool.handler(**call.args)
            else:
                output = await asyncio.to_thread(tool.handler, **call.args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_call_id=call.id,
                content=truncate(_describe(exc), self._max_error_chars),
                failed=True,
            )

        return ToolResult(
            tool_call_id=call.id, content=truncate(str(output), self._max_output_chars)
        )


def _describe(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _build(builder, args: Mapping):
    if builder is None:
        return None
    try:
        return builder(**args)
    except Exception:  # noqa: BLE001
        return None
