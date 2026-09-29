from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import BackgroundTask, BackgroundTaskCreate, TaskStatus

CreateTaskFn = Callable[[BackgroundTaskCreate], Awaitable[BackgroundTask]]
GetTaskByIdFn = Callable[[UUID], Awaitable[BackgroundTask | None]]
ListTasksForUserFn = Callable[[UUID], Awaitable[Sequence[BackgroundTask]]]
ListUnreportedFn = Callable[[UUID], Awaitable[Sequence[BackgroundTask]]]
MarkReportedFn = Callable[[Sequence[UUID]], Awaitable[None]]


class GetTaskForUserFn(Protocol):
    async def __call__(self, task_id: UUID, user_id: UUID) -> BackgroundTask | None: ...


class FinishTaskFn(Protocol):
    async def __call__(
        self, task_id: UUID, status: TaskStatus, result: str
    ) -> BackgroundTask | None: ...
