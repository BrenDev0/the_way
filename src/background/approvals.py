"""The user's side of a task that stopped for their approval (see paused.py)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache.ports import CacheStore
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.tools.domain import ClientRequest, Decision

from . import paused
from .domain import BackgroundTask, TaskStatus
from .sqlalchemy import adapter
from .use_cases import FAILURE_MARKER

EXPIRED = (
    f"{FAILURE_MARKER} -- it stopped to ask the user's approval and nobody answered within "
    "7 days, so it was dropped. Nothing after that point was done; offer to run it again."
)


async def waiting_on(
    session: AsyncSession, cache: CacheStore, task: BackgroundTask
) -> tuple[BackgroundTask, tuple[ClientRequest, ...]]:
    """What a waiting task asks. One whose saved run has expired is failed here, the first
    time anyone looks -- there is nothing left to resume it from."""
    if task.status is not TaskStatus.NEEDS_APPROVAL:
        return task, ()
    run = await paused.load(cache, task.id)
    if run is None:
        return await adapter.finish(session, task.id, TaskStatus.FAILED, EXPIRED) or task, ()
    return task, run.asking


async def approve(
    session: AsyncSession,
    cache: CacheStore,
    task_id: UUID,
    user_id: UUID,
    resolutions: Sequence[tuple[str, bool, str, dict[str, str]]],
) -> BackgroundTask:
    """Records the answers (tool call id, approved, feedback, picks) and sets the task
    running again; the caller enqueues it once this is committed."""
    task = await adapter.get_for_user(session, task_id, user_id)
    if task is None:
        raise NotFoundError(message="Background task not found", code="background_task_not_found")
    if task.status is not TaskStatus.NEEDS_APPROVAL:
        raise ConflictError(
            message="This task is not waiting for an approval", code="task_not_awaiting_approval"
        )

    run = await paused.load(cache, task.id)
    if run is None:
        await adapter.finish(session, task.id, TaskStatus.FAILED, EXPIRED)
        raise ConflictError(
            message="This approval expired after 7 days; the task was stopped",
            code="task_approval_expired",
        )

    asking = {request.call.id for request in run.asking}
    decisions = {
        call_id: Decision(approved=approved, feedback=feedback, args=args)
        for call_id, approved, feedback, args in resolutions
        if call_id in asking
    }
    missing = asking - decisions.keys()
    if missing:
        raise ValidationError(
            message=f"Every pending call must be answered together; missing: {', '.join(sorted(missing))}",
            code="task_approval_incomplete",
        )

    await paused.save(cache, task.id, paused.answered(run, decisions))
    await adapter.set_status(session, task.id, TaskStatus.RUNNING)
    return await adapter.get_by_id(session, task.id) or task
