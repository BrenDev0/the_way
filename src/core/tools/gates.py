from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .domain import ClientActionRequired, ClientRequest, Decision


class DenyGate:
    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=False) for _ in requests)


class AutoApproveGate:
    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        return tuple(Decision(approved=True) for _ in requests)


class AskOnlyGate:
    """A run with nobody watching: approves what it can itself, and suspends on any call to
    a tool that must always ask -- the run is saved and resumes once the user answers."""

    def __init__(self, always_ask: frozenset[str]) -> None:
        self._always_ask = always_ask

    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        asking = tuple(request for request in requests if request.call.name in self._always_ask)
        if asking:
            # only these are put to the user; the rest are approved here when the run resumes
            raise ClientActionRequired(asking)
        return tuple(Decision(approved=True) for _ in requests)


@dataclass
class Allowance:
    """What one approval let through for the rest of a run: this many more items (images),
    made with the option the user picked (the model)."""

    remaining: int
    args: dict[str, str] = field(default_factory=dict)


class AllowanceGate(AskOnlyGate):
    """A background run's gate once the user has approved its first image: further calls
    that must ask go through on their own -- with the user's picks -- while the allowance
    lasts, and the run suspends again only when it runs out."""

    def __init__(
        self,
        always_ask: frozenset[str],
        allowance: Allowance | None,
        cost: Callable[[ClientRequest], int],
    ) -> None:
        super().__init__(always_ask)
        self.allowance = allowance
        self._cost = cost

    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        asking = [request for request in requests if request.call.name in self._always_ask]
        needed = sum(self._cost(request) for request in asking)
        if asking and self.allowance and needed <= self.allowance.remaining:
            self.allowance.remaining -= needed
            picks = dict(self.allowance.args)
            return tuple(
                Decision(approved=True, args=picks if request in asking else {}) for request in requests
            )
        return await super().decide(requests)


class SuspendGate:
    """Hands the calls to the client: the turn stops here and resumes once the client has
    approved, rejected, or (for desktop tools) run each one and posted what it returned."""

    async def decide(self, requests: Sequence[ClientRequest]) -> tuple[Decision, ...]:
        raise ClientActionRequired(tuple(requests))
