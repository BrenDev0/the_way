from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from src.users.domain import User, UserCreate

CreateUserFn = Callable[[UserCreate], Awaitable[User]]
GetUserByIdFn = Callable[[UUID], Awaitable[User | None]]
GetUserByEmailHashFn = Callable[[str], Awaitable[User | None]]
ListUsersFn = Callable[[], Awaitable[Sequence[User]]]
DeleteUserFn = Callable[[UUID], Awaitable[bool]]
