import re
from collections.abc import Sequence
from uuid import UUID

from src.core.exceptions import ApplicationError, NotFoundError
from src.projects import config as projects_config
from src.projects.domain import Folder, ProjectFile
from src.projects.files import ProjectFiles

from . import config
from .domain import BackgroundTask, TaskStatus
from .ports import GetTaskForUserFn, ListTasksForUserFn

# A run reports failure by returning, not raising. The result starts with this so the
# assistant relaying it cannot mistake an unfinished task for a finished one.
FAILURE_MARKER = "TASK FAILED"

# Injected on the turn a task's result is first relayed. Both forms carry the same
# verified output; only the first asks for it to be reported, and only the second is kept
# in the conversation -- left as a live notice, it would be announced again every turn.
TASK_NOTICE = (
    "A background task finished while the user was away from this conversation. The "
    "result below is the worker's complete, verified output. Report it in THIS reply and "
    "nowhere else: do not extend, embellish, or substitute your own content, and if the "
    "result does not contain the requested deliverable, say so plainly.\n{news}"
)

# Heads the notice when the server opened the turn itself to report a finished task:
# the user did not write it and is not waiting on a question.
AUTOMATIC = (
    "[Automatic message from the system, not from the user: a background task you started "
    "has finished. Tell the user about it now, in their language, without waiting to be "
    "asked -- briefly, with what was produced and where it is. Do not ask a question unless "
    "the result needs a decision from them.]"
)

TASK_RELAYED = (
    "[already reported to the user -- do not announce this again] A background task "
    "finished earlier and its result was passed on. Kept only so you can refer back to "
    "the file paths in it:\n{news}"
)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Background task not found", code="background_task_not_found")


def task_path(task: BackgroundTask) -> str:
    return f"{config.TASKS_FOLDER}/{task.folder}"


def delivery_target(task: BackgroundTask) -> tuple[str, str] | None:
    """Where the finished files go: the folder the user named, or for work sent to the
    drafts project, a folder of the task's own -- so one draft never lands on another."""
    if not task.deliver_project:
        return None
    if task.deliver_path and task.deliver_path.strip("/."):
        return task.deliver_project, task.deliver_path
    if task.deliver_project.strip().lower() == projects_config.DRAFTS_PROJECT.lower():
        return task.deliver_project, task.folder
    return task.deliver_project, "."


async def get_task(
    task_id: UUID, user_id: UUID, get_task_for_user_fn: GetTaskForUserFn
) -> BackgroundTask:
    task = await get_task_for_user_fn(task_id, user_id)
    if task is None:
        raise _not_found()
    return task


async def list_tasks(
    user_id: UUID, list_tasks_for_user_fn: ListTasksForUserFn
) -> Sequence[BackgroundTask]:
    return await list_tasks_for_user_fn(user_id)


def news(tasks: Sequence[BackgroundTask]) -> str:
    return "\n".join(
        f"[{task.id}] {task.description} -- {task.status}: {task.result}" for task in tasks
    )


async def produced(files: ProjectFiles, task: BackgroundTask) -> str:
    """What is actually in the task folder. The worker's own report is not evidence a
    file exists; this is -- and it lists paths relative to the folder, so a worker that
    wrapped everything in a stray subfolder shows up as one."""
    prefix = f"{task_path(task)}/"
    try:
        workspace = await files.workspace()
        entries = await files.tree(workspace)
    except ApplicationError:
        entries = []

    found = sorted(
        path[len(prefix) :]
        for path, entry in entries
        if path.startswith(prefix) and not isinstance(entry, Folder)
    )
    if not found:
        return f"NO FILES were written to .the_way/{prefix}."
    return f"Files in .the_way/{prefix}: {', '.join(found)}."


def _same_name(a: str, b: str) -> bool:
    """Folder names compared the way a person would: 'client_report', 'client-report' and
    'Client Report' are all the same folder."""
    squashed = [re.sub(r"[^a-z0-9]+", "", name.lower()) for name in (a, b)]
    return squashed[0] == squashed[1] != ""


async def deliver(
    files: ProjectFiles, task: BackgroundTask, project_name: str, destination: str
) -> str:
    """Copy a task's output into a folder the user can reach.

    Copy, not move: the task folder stays as the record of what was produced, so a delivery
    can be repeated. Done by the runtime rather than by a model -- the bytes never pass
    through anyone's context, so what lands is exactly what the worker wrote.

    A worker told its output is going to 'dashboard' often creates dashboard/ inside its
    own folder, which would deliver as dashboard/dashboard/. When the whole task folder is
    one directory named after the destination, only its contents are copied.
    """
    workspace = await files.workspace()
    target = await files.project(project_name)

    root = task_path(task)
    destination_name = destination.strip("/").split("/")[-1] if destination.strip("/.") else ""
    for _ in range(3):  # dashboard/dashboard/dashboard has been seen in the wild
        contents = await files.contents(workspace, root)
        only = (*contents.folders, *contents.files)
        if len(only) == 1 and isinstance(only[0], Folder) and _same_name(only[0].name, destination_name):
            root = f"{root}/{only[0].name}"
        else:
            break

    contents = await files.contents(workspace, root)
    children: list[Folder | ProjectFile] = [*contents.folders, *contents.files]
    if not children:
        return f"Nothing to deliver -- .the_way/{task_path(task)}/ is empty."

    if destination.strip("/."):
        await files.make_folder(target, destination)

    delivered = []
    for child in children:
        # a revision lands on the file it revises -- that is what delivering it means
        count, landed = await files.copy(workspace, f"{root}/{child.name}", target, destination, replace=True)
        delivered.append(f"{landed} ({count} file{'' if count == 1 else 's'})")

    unwrapped = (
        "" if root == task_path(task)
        else f" (dropped the redundant {root[len(task_path(task)) + 1:]}/ level the worker added)"
    )
    return f"Delivered to {target.name}/{destination.strip('/') or '.'}{unwrapped}: {', '.join(delivered)}"


def reports_incomplete(report: str) -> bool:
    """The worker's own verdict, on the first line of its report: RESULT: INCOMPLETE when
    the main thing asked for was not made. Without it a task that wrote a note saying the
    edit failed counted as done -- a green check over a failure. A report with no verdict
    line is taken as complete, as before."""
    first = next((line for line in report.splitlines() if line.strip()), "")
    verdict = first.strip().strip("*").strip().lower()
    return verdict.startswith("result:") and verdict.removeprefix("result:").strip().startswith("incomplete")


def status_of(result: str) -> TaskStatus:
    return TaskStatus.FAILED if result.startswith(FAILURE_MARKER) else TaskStatus.DONE
