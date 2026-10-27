from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import BackgroundTask, BackgroundTaskCreate, TaskStatus

CreateTaskFn = Callable[[BackgroundTaskCreate], Awaitable[BackgroundTask]]
GetTaskByIdFn = Callable[[UUID], Awaitable[BackgroundTask | None]]
ListTasksForUserFn = Callable[[UUID], Awaitable[Sequence[BackgroundTask]]]
ListUnreportedFn = Callable[[UUID], Awaitable[Sequence[BackgroundTask]]]
MarkReportedFn = Callable[[Sequence[UUID]], Awaitable[None]]
# task id, user id: stops or resumes the user's own task, committed on its own (the agent's
# tools run inside the turn's transaction, which the worker cannot see)
StopTaskFn = Callable[[UUID, UUID], Awaitable[BackgroundTask]]
ResumeTaskFn = Callable[[UUID, UUID], Awaitable[BackgroundTask]]


class GetTaskForUserFn(Protocol):
    async def __call__(self, task_id: UUID, user_id: UUID) -> BackgroundTask | None: ...


class FinishTaskFn(Protocol):
    async def __call__(
        self, task_id: UUID, status: TaskStatus, result: str
    ) -> BackgroundTask | None: ...
