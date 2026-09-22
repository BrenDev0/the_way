import asyncio
import inspect
from collections.abc import Mapping, Sequence

from src.core.llm.domain import ToolCall

from .domain import (
    MAX_ERROR_CHARS,
    UNKNOWN_TOOL,
    ApprovalRequest,
    Decision,
    Tool,
    ToolResult,
    truncate,
)
from .ports import ApprovalGate, ToolEvents


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
    ) -> None:
        self._tools = dict(tools)
        self._gate = gate
        self._events = events or NullEvents()
        self._max_error_chars = max_error_chars

    def requires_approval(self, call: ToolCall) -> bool:
        tool = self._tools.get(call.name)
        return bool(tool and tool.requires_approval)

    async def execute(
        self,
        calls: Sequence[ToolCall],
        decisions: Mapping[str, Decision] | None = None,
    ) -> tuple[ToolResult, ...]:
        decided = dict(decisions or {})
        undecided = [
            call
            for call in calls
            if self.requires_approval(call) and call.id not in decided
        ]

        if undecided:
            requests = tuple(self._approval_request(call) for call in undecided)
            for call, decision in zip(undecided, await self._gate.decide(requests), strict=True):
                decided[call.id] = decision

        results = await asyncio.gather(
            *(self._run(call, decided.get(call.id)) for call in calls)
        )
        return tuple(results)

    def _approval_request(self, call: ToolCall) -> ApprovalRequest:
        tool = self._tools[call.name]
        return ApprovalRequest(
            call=call,
            preview=_build(tool.preview, call.args),
            detail=_build(tool.describe, call.args),
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

        await self._events.tool_started(call)
        result = await self._invoke(tool, call)
        await self._events.tool_finished(call, result)
        return result

    async def _invoke(self, tool: Tool, call: ToolCall) -> ToolResult:
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

        return ToolResult(tool_call_id=call.id, content=str(output))


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
