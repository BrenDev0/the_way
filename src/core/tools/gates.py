from collections.abc import Sequence

from .domain import ApprovalRequest, Decision


class DenyGate:
    async def decide(self, requests: Sequence[ApprovalRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=False) for _ in requests)


class AutoApproveGate:
    async def decide(self, requests: Sequence[ApprovalRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=True) for _ in requests)
