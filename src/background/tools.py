from collections.abc import Awaitable, Callable
from uuid import UUID

from src.core.database.sqlalchemy.core import async_session_factory
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects import config as projects_config
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
        # Unless the user named a folder, finished work goes to the drafts project rather
        # than being left in the workspace they never browse.
        deliver_to_project = (deliver_to_project or "").strip() or projects_config.DRAFTS_PROJECT
        # checked now, while someone can still answer -- a wrong name found after the work
        # is done means a finished deliverable with nowhere to go
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

        project, path = background_use_cases.delivery_target(task) or (deliver_to_project, ".")
        return (
            f"Started background task {task.id}: {description}. Working files go to "
            f".the_way/{background_use_cases.task_path(task)}/, and the finished files will "
            f"be delivered to {project}/{path.strip('/.') or '.'} automatically."
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
        if task.status is TaskStatus.NEEDS_APPROVAL:
            return (
                f"Task {task_id} is waiting for the user to approve a step (an image, say) in "
                "the app. It carries on once they answer; deliver it after that."
            )

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
