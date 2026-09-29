from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from src.auth import dependencies as auth_dependencies
from src.users.domain import User

from . import dependencies as background_dependencies
from . import mapper
from . import use_cases as background_use_cases
from .ports import GetTaskForUserFn, ListTasksForUserFn
from .schemas import BackgroundTaskResponse

router = APIRouter(tags=["background-tasks"])

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]


@router.get("", response_model=list[BackgroundTaskResponse])
async def list_background_tasks_route(
    current_user: CurrentUser,
    list_tasks_for_user_fn: Annotated[
        ListTasksForUserFn,
        Depends(background_dependencies.provide_list_tasks_for_user_fn),
    ],
) -> list[BackgroundTaskResponse]:
    tasks = await background_use_cases.list_tasks(
        user_id=current_user.id, list_tasks_for_user_fn=list_tasks_for_user_fn
    )
    return [mapper.domain_to_task_response(task) for task in tasks]


@router.get("/{task_id}", response_model=BackgroundTaskResponse)
async def get_background_task_route(
    task_id: UUID,
    current_user: CurrentUser,
    get_task_for_user_fn: Annotated[
        GetTaskForUserFn,
        Depends(background_dependencies.provide_get_task_for_user_fn),
    ],
) -> BackgroundTaskResponse:
    task = await background_use_cases.get_task(
        task_id=task_id, user_id=current_user.id, get_task_for_user_fn=get_task_for_user_fn
    )
    return mapper.domain_to_task_response(task)
