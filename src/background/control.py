"""The user's side of stopping and resuming a background task.

A task that is running is stopped by a flag its worker reads between steps (core/stop.py); the
worker then keeps the run (paused.py) and marks the task stopped. A task waiting on the user's
approval has no worker, so it is stopped here, with its saved run left as it was: resumed, it
asks again. A stopped task is resumed from its saved run, with a note to the worker that it was
stopped.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core import stop as stop_signal
from src.core.cache.ports import CacheStore
from src.core.exceptions import ConflictError, NotFoundError

from . import use_cases
from .domain import BackgroundTask, TaskStatus
from .sqlalchemy import adapter


async def _own(session: AsyncSession, task_id: UUID, user_id: UUID) -> BackgroundTask:
    task = await adapter.get_for_user(session, task_id, user_id)
    if task is None:
        raise NotFoundError(message="Background task not found", code="background_task_not_found")
    return task


async def stop(session: AsyncSession, cache: CacheStore, task_id: UUID, user_id: UUID) -> BackgroundTask:
    """Asks a running task to stop, or stops one waiting on an approval. For a running task
    the status changes when its worker reaches a safe point, a moment later: the returned
    task is still 'running'."""
    task = await _own(session, task_id, user_id)

    if task.status is TaskStatus.RUNNING:
        await stop_signal.request(cache, stop_signal.task_key(task.id))
        return task

    if task.status is TaskStatus.NEEDS_APPROVAL:
        await adapter.finish(session, task.id, TaskStatus.STOPPED, use_cases.stopped_result(""))
        return await adapter.get_by_id(session, task.id) or task

    raise ConflictError(
        message="This task is not running, so there is nothing to stop",
        code="task_not_running",
    )


async def resume(session: AsyncSession, cache: CacheStore, task_id: UUID, user_id: UUID) -> BackgroundTask:
    """Sets a stopped task running again; the caller enqueues it once this is committed. Its
    outcome is reported to the conversation afresh, as the stop already was."""
    task = await _own(session, task_id, user_id)
    if task.status is not TaskStatus.STOPPED:
        raise ConflictError(
            message="This task is not stopped, so there is nothing to resume",
            code="task_not_stopped",
        )

    await stop_signal.clear(cache, stop_signal.task_key(task.id))
    await adapter.reopen(session, task.id)
    return await adapter.get_by_id(session, task.id) or task
