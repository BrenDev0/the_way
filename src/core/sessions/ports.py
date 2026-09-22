from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from .domain import Session, SessionCreate

CreateSessionFn = Callable[[SessionCreate], Awaitable[Session]]
GetSessionByTokenHashFn = Callable[[str], Awaitable[Session | None]]
TouchSessionFn = Callable[[UUID], Awaitable[Session | None]]
RevokeSessionFn = Callable[[UUID], Awaitable[bool]]
RevokeSessionByTokenHashFn = Callable[[str], Awaitable[bool]]
RevokeSessionsByUserIdFn = Callable[[UUID], Awaitable[int]]
ListActiveSessionsByUserIdFn = Callable[[UUID], Awaitable[Sequence[Session]]]
