from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .domain import Session, SessionCreate

CreateSessionFn = Callable[[SessionCreate], Awaitable[Session]]
GetSessionByTokenHashFn = Callable[[str], Awaitable[Session | None]]
TouchSessionFn = Callable[[UUID], Awaitable[Session | None]]
RevokeSessionFn = Callable[[UUID], Awaitable[bool]]
RevokeSessionByTokenHashFn = Callable[[str], Awaitable[bool]]
RevokeSessionsByUserIdFn = Callable[[UUID], Awaitable[int]]
ListActiveSessionsByUserIdFn = Callable[[UUID], Awaitable[Sequence[Session]]]


class RenewSessionFn(Protocol):
    """Touch a session and push its expiry out -- a sliding window, so a device in use
    stays signed in and one left idle signs itself out."""

    async def __call__(self, session_id: UUID, expires_at: datetime) -> Session | None: ...


class RevokeSessionForUserFn(Protocol):
    async def __call__(self, session_id: UUID, user_id: UUID) -> bool: ...
