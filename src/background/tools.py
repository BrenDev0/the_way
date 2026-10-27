from collections.abc import Awaitable, Callable
from uuid import UUID

from src.assistants.context import ToolContext
from src.core.exceptions import ConflictError, NotFoundError
from src.core.tools.domain import Tool
from src.projects import config as projects_config

from . import use_cases as background_use_cases
from .domain import BackgroundTaskCreate, TaskStatus
from .tool_schemas import (
    CheckBackgroundTask,
    DeliverTask,
    ResumeBackgroundTask,
    StartBackgroundTask,
    StopBackgroundTask,
)

Enqueue = Callable[[UUID], Awaitable[object]]

UNKNOWN_SKILLS = (
    "No task was started: this organization has no skill named {unknown}. Its skills: "
    "{held}. Call again with names exactly as listed, or without skills if none applies."
)


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
) -> dict[str, Tool]:
    files = context.files

    async def start_background_task(
        description: str,
        instructions: str,
        deliver_to_project: str | None = None,
        deliver_to_path: str | None = None,
        skills: list[str] | None = None,
    ) -> str:
        # Unless the user named a folder, finished work goes to the drafts project rather
        # than being left in the workspace they never browse.
        deliver_to_project = (deliver_to_project or "").strip() or projects_config.DRAFTS_PROJECT
        # checked now, while someone can still answer -- a wrong name found after the work
        # is done means a finished deliverable with nowhere to go
        await files.project(deliver_to_project)

        # Likewise a skill name: a worker told to follow a skill that is not there would
        # improvise and report it as done the skill's way.
        named = list(dict.fromkeys(name.strip() for name in skills or [] if name.strip()))
        if named:
            held = {
                skill.name
                for skill in await context.ports.list_skills_fn(context.organization_id)
            }
            unknown = [name for name in named if name not in held]
            if unknown:
                return UNKNOWN_SKILLS.format(
                    unknown=", ".join(unknown), held=", ".join(sorted(held)) or "none"
                )
            instructions = background_use_cases.with_skills(instructions, named)

        # Committed on its own, apart from the turn: the worker picks the task up in
        # seconds, and the turn may not commit for minutes.
        task = await context.ports.create_task_fn(
            BackgroundTaskCreate(
                organization_id=context.organization_id,
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                description=description,
                instructions=instructions,
                deliver_project=deliver_to_project,
                deliver_path=deliver_to_path,
            )
        )

        await enqueue(task.id)

        project, path = background_use_cases.delivery_target(task) or (deliver_to_project, ".")
        return (
            f"Started background task {task.id}: {description}. Working files go to "
            f".the_way/{background_use_cases.task_path(task)}/, and the finished files will "
            f"be delivered to {project}/{path.strip('/.') or '.'} automatically."
        )

    async def check_background_task(task_id: str) -> str:
        parsed = _parse(task_id)
        task = await context.ports.get_task_for_user_fn(parsed, context.user_id) if parsed else None
        if task is None:
            return f"Task with id {task_id} not found"

        response = (
            f"Task status is {task.status}. Working folder: "
            f".the_way/{background_use_cases.task_path(task)}/"
        )
        if task.result:
            response += f"\nThe result of the task is: {task.result}"
            await context.ports.mark_reported_fn([task.id])
        return response

    async def deliver_task(task_id: str, project: str, path: str = ".") -> str:
        parsed = _parse(task_id)
        task = await context.ports.get_task_for_user_fn(parsed, context.user_id) if parsed else None
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

    async def stop_background_task(task_id: str) -> str:
        parsed = _parse(task_id)
        stop = context.ports.stop_task_fn
        if parsed is None or stop is None:
            return f"Task with id {task_id} not found. Ask the user which task they mean."
        try:
            task = await stop(parsed, context.user_id)
        except (NotFoundError, ConflictError) as exc:
            return f"Not stopped: {exc.message}."
        # the user asked for this in the conversation, so the agent knows: not told again later
        await context.ports.mark_reported_fn([task.id])
        if task.status is TaskStatus.STOPPED:
            return (
                f"Task {task.id} is stopped. What it made stays in "
                f".the_way/{background_use_cases.task_path(task)}/, and it can be resumed with "
                "ResumeBackgroundTask if the user wants it to carry on."
            )
        return (
            f"Stop requested for task {task.id}: it ends at its next step, in a moment, and keeps "
            "its place and its files. Do not say it has stopped yet; CheckBackgroundTask shows "
            "when it has."
        )

    async def resume_background_task(task_id: str) -> str:
        parsed = _parse(task_id)
        resume = context.ports.resume_task_fn
        if parsed is None or resume is None:
            return f"Task with id {task_id} not found. Ask the user which task they mean."
        try:
            task = await resume(parsed, context.user_id)
        except (NotFoundError, ConflictError) as exc:
            return f"Not resumed: {exc.message}."
        await enqueue(task.id)
        return (
            f"Task {task.id} is running again from where it stopped: {task.description}. You will "
            "be told when it finishes."
        )

    tools = {
        StartBackgroundTask.__name__: Tool(schema=StartBackgroundTask, handler=start_background_task),
        CheckBackgroundTask.__name__: Tool(schema=CheckBackgroundTask, handler=check_background_task),
        DeliverTask.__name__: Tool(schema=DeliverTask, handler=deliver_task),
    }
    # only where there is a way to reach the worker (a cache to ask it through)
    if context.ports.stop_task_fn is not None:
        tools[StopBackgroundTask.__name__] = Tool(schema=StopBackgroundTask, handler=stop_background_task)
    if context.ports.resume_task_fn is not None:
        tools[ResumeBackgroundTask.__name__] = Tool(schema=ResumeBackgroundTask, handler=resume_background_task)
    return tools


async def drain_notices(context: ToolContext) -> str:
    """Tasks this conversation started that finished since the last turn, marked reported
    in the turn's own transaction -- so a turn that fails leaves them to be told next time."""
    if context.conversation_id is None:
        return ""

    finished = await context.ports.list_unreported_fn(context.conversation_id)
    await context.ports.mark_reported_fn([task.id for task in finished])
    return background_use_cases.news(finished)
