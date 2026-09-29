from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from src.api_keys import credentials as api_keys_credentials
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.assistants.catalog import server_tools
from src.conversations.events import ConversationEvents
from src.core.agents.runner import AssistantRun, run_assistant
from src.core.bucket.ports import BucketStore
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.events.ports import EventStream
from src.core.llm import domain as llm_domain
from src.core.tasks.broker import broker
from src.core.tools.context import LLMFactory, ToolContext
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate
from src.core.tools.ports import ToolEvents
from src.projects.files import ProjectFiles
from src.users.sqlalchemy import adapter as users_adapter
from src.worker import dependencies as worker_dependencies

from . import config
from . import use_cases as background_use_cases
from .domain import BackgroundTask, TaskStatus
from .prompt import SYSTEM_PROMPT
from .sqlalchemy import adapter


@broker.task
async def run_background_task(
    task_id: UUID,
    encryption_service: Annotated[
        EncryptionService,
        TaskiqDepends(worker_dependencies.get_encryption_service),
    ],
    bucket_store: Annotated[
        BucketStore,
        TaskiqDepends(worker_dependencies.get_bucket_store),
    ],
    event_stream: Annotated[
        EventStream,
        TaskiqDepends(worker_dependencies.get_event_stream),
    ],
) -> str | None:
    return await run_task(
        task_id, bucket_store, encryption_service=encryption_service, event_stream=event_stream
    )


async def run_task(
    task_id: UUID,
    bucket_store: BucketStore,
    encryption_service: EncryptionService | None = None,
    llm_factory: LLMFactory | None = None,
    event_stream: EventStream | None = None,
) -> str | None:
    events: ConversationEvents | None = None
    task: BackgroundTask | None = None
    async with async_session_factory() as session:
        try:
            task = await adapter.get_by_id(session, task_id)
            if task is None or task.status is not TaskStatus.RUNNING:
                return None

            # told on the conversation that started it, where the user is watching
            if event_stream is not None and task.conversation_id is not None:
                events = ConversationEvents(event_stream, task.conversation_id, task_id=task.id)
                await events.task_started(task.id, task.description)

            context = await _context(session, task, bucket_store, encryption_service, llm_factory, events)
            files = ProjectFiles(session, task.organization_id, task.user_id, bucket_store)
            await files.make_folder(await files.workspace(), background_use_cases.task_path(task))

            result = await _work(context, files, task)
            status = background_use_cases.status_of(result)

            # deliver only on success -- copying a half-finished deliverable into the
            # user's project is worse than leaving it in the task folder, because it
            # looks finished
            if status is TaskStatus.DONE and task.deliver_project:
                result = f"{result}\n{await _deliver(files, task)}"

            await adapter.finish(session, task.id, status, result)
            await session.commit()
            if events:
                await events.task_finished(task.id, task.description, str(status))
            return str(status)
        except Exception as exc:
            await session.rollback()
            await _mark_failed(task_id, f"{background_use_cases.FAILURE_MARKER} -- {type(exc).__name__}: {exc}")
            if events and task:
                await events.task_finished(task.id, task.description, str(TaskStatus.FAILED))
            raise


async def _context(
    session: AsyncSession,
    task: BackgroundTask,
    bucket_store: BucketStore,
    encryption_service: EncryptionService | None,
    llm_factory: LLMFactory | None,
    events: ToolEvents | None = None,
) -> ToolContext:
    user = await users_adapter.get_user_by_id(session, task.user_id)
    if user is None:
        raise RuntimeError("the user who started this task no longer exists")

    credentials = {}
    if encryption_service is not None:

        async def list_api_keys_for_user_fn(uid: UUID):
            return await api_keys_adapter.list_for_user(session, uid)

        credentials = await api_keys_credentials.load_credentials(
            task.user_id, list_api_keys_for_user_fn, encryption_service
        )

    return ToolContext(
        session=session,
        organization_id=task.organization_id,
        user_id=task.user_id,
        user_role=str(user.role),
        bucket_store=bucket_store,
        credentials=credentials,
        llm_factory=llm_factory or api_keys_credentials.build_llm_factory(credentials),
        conversation_id=task.conversation_id,
        events=events,
    )


async def _work(context: ToolContext, files: ProjectFiles, task: BackgroundTask) -> str:
    tools = {name: tool for name, tool in server_tools(context).items() if name in config.TOOLS}
    llm = await context.llm_factory(config.MODELS, config.TEMPERATURE)

    run: AssistantRun = await run_assistant(
        llm,
        Executor(tools, AutoApproveGate(), context.events),
        [
            llm_domain.system(SYSTEM_PROMPT),
            llm_domain.user(
                f"Task folder: .the_way/{background_use_cases.task_path(task)}/\n\n"
                f"Task:\n{task.instructions}"
            ),
        ],
        config.MAX_ITERATIONS,
    )

    produced = await background_use_cases.produced(files, task)
    if not run.finished:
        return (
            f"{background_use_cases.FAILURE_MARKER} -- the worker ran out of steps before "
            f"finishing. {produced} It reported: {run.text} Tell the user plainly that it did "
            f"not complete; do not describe it as finished."
        )
    return f"{produced}\n{run.text}"


async def _deliver(files: ProjectFiles, task: BackgroundTask) -> str:
    try:
        return await background_use_cases.deliver(
            files, task, task.deliver_project or "", task.deliver_path or "."
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"Delivery to {task.deliver_project}/{task.deliver_path or ''} FAILED "
            f"({type(exc).__name__}: {exc}). The files are still in "
            f".the_way/{background_use_cases.task_path(task)}/ -- tell the user the delivery "
            f"failed and offer to retry it with DeliverTask."
        )


async def _mark_failed(task_id: UUID, result: str) -> None:
    async with async_session_factory() as session:
        await adapter.finish(session, task_id, TaskStatus.FAILED, result)
        await session.commit()
