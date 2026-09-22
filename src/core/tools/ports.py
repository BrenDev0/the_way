from collections.abc import Mapping, Sequence
from typing import Protocol

from src.core.llm.domain import ToolCall

from .domain import ApprovalRequest, Decision, ToolResult


class ApprovalGate(Protocol):
    async def decide(self, requests: Sequence[ApprovalRequest]) -> tuple[Decision, ...]: ...


class ToolEvents(Protocol):
    async def tool_started(self, call: ToolCall) -> None: ...

    async def tool_finished(self, call: ToolCall, result: ToolResult) -> None: ...


class ToolExecutor(Protocol):
    async def execute(
        self,
        calls: Sequence[ToolCall],
        decisions: Mapping[str, Decision] | None = None,
    ) -> tuple[ToolResult, ...]: ...

    def requires_approval(self, call: ToolCall) -> bool: ...
