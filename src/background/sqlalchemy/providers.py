from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.background.ports import GetTaskForUserFn, ListTasksForUserFn
from src.core.database.sqlalchemy import dependencies as db_dependencies

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_list_tasks_for_user_fn(session: Session) -> ListTasksForUserFn:
    async def list_tasks_for_user_fn(user_id: UUID):
        return await adapter.list_for_user(session, user_id)

    return list_tasks_for_user_fn


def provide_get_task_for_user_fn(session: Session) -> GetTaskForUserFn:
    async def get_task_for_user_fn(task_id: UUID, user_id: UUID):
        return await adapter.get_for_user(session, task_id, user_id)

    return get_task_for_user_fn
