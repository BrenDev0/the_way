from collections.abc import Sequence

from .domain import ClientActionRequired, ClientRequest, Decision


class DenyGate:
    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=False) for _ in requests)


class AutoApproveGate:
    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=True) for _ in requests)


class SuspendGate:
    """Hands the calls to the client: the turn stops here and resumes once the client has
    approved, rejected, or (for desktop tools) run each one and posted what it returned."""

    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        raise ClientActionRequired(tuple(requests))
