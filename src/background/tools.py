from collections.abc import Awaitable, Callable
from uuid import UUID

from src.core.database.sqlalchemy.core import async_session_factory
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects.files import ProjectFiles

from . import use_cases as background_use_cases
from .domain import BackgroundTaskCreate, TaskStatus
from .sqlalchemy import adapter
from .tool_schemas import CheckBackgroundTask, DeliverTask, StartBackgroundTask

Enqueue = Callable[[UUID], Awaitable[object]]


async def _enqueue(task_id: UUID) -> object:
    from .jobs import run_background_task

    return await run_background_task.kiq(task_id)  # type: ignore[call-overload]


def _parse(task_id: str) -> UUID | None:
    try:
        return UUID(task_id.strip())
    except ValueError:
        return None


def build(
    context: ToolContext,
    enqueue: Enqueue = _enqueue,
    session_factory=async_session_factory,
) -> dict[str, Tool]:
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )

    async def start_background_task(
        description: str,
        instructions: str,
        deliver_to_project: str | None = None,
        deliver_to_path: str | None = None,
    ) -> str:
        if deliver_to_project:
            # checked now, while someone can still answer -- a wrong name found after the
            # work is done means a finished deliverable with nowhere to go
            await files.project(deliver_to_project)

        # Committed in its own session, not the turn's: the worker picks the task up in
        # seconds, and the turn may not commit for minutes.
        async with session_factory() as session:
            task = await adapter.create(
                session,
                BackgroundTaskCreate(
                    organization_id=context.organization_id,
                    user_id=context.user_id,
                    conversation_id=context.conversation_id,
                    description=description,
                    instructions=instructions,
                    deliver_project=deliver_to_project,
                    deliver_path=deliver_to_path,
                ),
            )
            await session.commit()

        await enqueue(task.id)

        started = (
            f"Started background task {task.id}: {description}. Working files go to "
            f".the_way/{background_use_cases.task_path(task)}/"
        )
        if deliver_to_project:
            where = f"{deliver_to_project}/{(deliver_to_path or '').strip('/') or '.'}"
            return f"{started}, and the finished files will be delivered to {where} automatically."
        return (
            f"{started}. No delivery folder was set, so the output will stay in the "
            f"'.the_way' workspace, which the user does not browse -- tell them that, and ask "
            f"where they want it so you can call DeliverTask with id {task.id}."
        )

    async def check_background_task(task_id: str) -> str:
        parsed = _parse(task_id)
        task = await adapter.get_for_user(context.session, parsed, context.user_id) if parsed else None
        if task is None:
            return f"Task with id {task_id} not found"

        response = (
            f"Task status is {task.status}. Working folder: "
            f".the_way/{background_use_cases.task_path(task)}/"
        )
        if task.result:
            response += f"\nThe result of the task is: {task.result}"
            await adapter.mark_reported(context.session, [task.id])
        return response

    async def deliver_task(task_id: str, project: str, path: str = ".") -> str:
        parsed = _parse(task_id)
        task = await adapter.get_for_user(context.session, parsed, context.user_id) if parsed else None
        if task is None:
            return (
                f"Task with id {task_id} not found. Do not guess a folder name -- ask the "
                "user which task they mean."
            )

        if task.status is TaskStatus.RUNNING:
            return f"Task {task_id} is still running. Wait for it to finish before delivering."

        delivered = await background_use_cases.deliver(files, task, project, path)
        if task.status is not TaskStatus.DONE:
            return (
                f"Task {task_id} ended as '{task.status}', so this may not be a finished "
                f"deliverable. {delivered}"
            )
        return delivered

    return {
        StartBackgroundTask.__name__: Tool(schema=StartBackgroundTask, handler=start_background_task),
        CheckBackgroundTask.__name__: Tool(schema=CheckBackgroundTask, handler=check_background_task),
        DeliverTask.__name__: Tool(schema=DeliverTask, handler=deliver_task),
    }


async def drain_notices(context: ToolContext) -> str:
    """Tasks this conversation started that finished since the last turn, marked reported
    in the turn's own transaction -- so a turn that fails leaves them to be told next time."""
    if context.conversation_id is None:
        return ""

    finished = await adapter.list_unreported(context.session, context.conversation_id)
    await adapter.mark_reported(context.session, [task.id for task in finished])
    return background_use_cases.news(finished)
