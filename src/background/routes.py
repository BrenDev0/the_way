from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.cache.ports import CacheStore
from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.users.domain import User

from . import approvals, mapper
from . import dependencies as background_dependencies
from . import use_cases as background_use_cases
from .ports import GetTaskForUserFn, ListTasksForUserFn
from .schemas import ApproveTaskRequest, BackgroundTaskResponse

router = APIRouter(tags=["background-tasks"])

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]
Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]
Cache = Annotated[CacheStore, Depends(api_dependencies.get_cache_store)]


async def _response(session: AsyncSession, cache: CacheStore, task) -> BackgroundTaskResponse:
    task, asking = await approvals.waiting_on(session, cache, task)
    return mapper.domain_to_task_response(task, asking)


@router.get("", response_model=list[BackgroundTaskResponse])
async def list_background_tasks_route(
    current_user: CurrentUser,
    session: Session,
    cache: Cache,
    list_tasks_for_user_fn: Annotated[
        ListTasksForUserFn,
        Depends(background_dependencies.provide_list_tasks_for_user_fn),
    ],
) -> list[BackgroundTaskResponse]:
    tasks = await background_use_cases.list_tasks(
        user_id=current_user.id, list_tasks_for_user_fn=list_tasks_for_user_fn
    )
    responses = [await _response(session, cache, task) for task in tasks]
    await session.commit()  # an expired approval found while listing is recorded as such
    return responses


@router.get("/{task_id}", response_model=BackgroundTaskResponse)
async def get_background_task_route(
    task_id: UUID,
    current_user: CurrentUser,
    session: Session,
    cache: Cache,
    get_task_for_user_fn: Annotated[
        GetTaskForUserFn,
        Depends(background_dependencies.provide_get_task_for_user_fn),
    ],
) -> BackgroundTaskResponse:
    task = await background_use_cases.get_task(
        task_id=task_id, user_id=current_user.id, get_task_for_user_fn=get_task_for_user_fn
    )
    response = await _response(session, cache, task)
    await session.commit()
    return response


@router.post(
    "/{task_id}/approvals",
    response_model=BackgroundTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_background_task_route(
    task_id: UUID,
    payload: ApproveTaskRequest,
    current_user: CurrentUser,
    session: Session,
    cache: Cache,
) -> BackgroundTaskResponse:
    """Answers what a task stopped to ask, and sets it going again from where it stopped."""
    from .jobs import run_background_task  # the worker module imports every tool

    try:
        task = await approvals.approve(
            session,
            cache,
            task_id,
            current_user.id,
            [(r.tool_call_id, r.approved, r.feedback, dict(r.args)) for r in payload.resolutions],
        )
    finally:
        # an approval found expired is recorded even though the request fails
        await session.commit()
    await run_background_task.kiq(task.id)  # type: ignore[call-overload]
    return mapper.domain_to_task_response(task)
