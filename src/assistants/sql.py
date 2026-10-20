"""Binds the tools' ports to the database.

The one place that connects a run's ToolContext to a session: the conversation worker and
the background worker call `sql_tool_context` once per run, and every tool after that works
through ports. (A test binds them to fakes instead.)
"""

from collections.abc import Mapping
from functools import partial
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.background.domain import BackgroundTask, BackgroundTaskCreate
from src.background.sqlalchemy import adapter as background_adapter
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.bucket.ports import BucketStore
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.tools.ports import ToolEvents
from src.documents.sqlalchemy import adapter as documents_adapter
from src.preferences.sqlalchemy import adapter as preferences_adapter
from src.projects.sqlalchemy import adapter as projects_adapter
from src.projects.sqlalchemy.store import project_files
from src.skills.sqlalchemy import adapter as skills_adapter

from .context import Credential, LLMFactory, ToolContext, ToolPorts


async def create_task_in_its_own_session(task: BackgroundTaskCreate) -> BackgroundTask:
    """Committed on its own, not with the turn: the worker picks the task up in seconds, and
    the turn may not commit for minutes."""
    async with async_session_factory() as session:
        created = await background_adapter.create(session, task)
        await session.commit()
        return created


def sql_tool_ports(session: AsyncSession) -> ToolPorts:
    return ToolPorts(
        list_skills_fn=partial(skills_adapter.list_for_organization, session),
        get_skill_fn=partial(skills_adapter.get_for_organization, session),
        count_skills_fn=partial(skills_adapter.count_for_organization, session),
        upsert_skill_fn=partial(skills_adapter.upsert, session),
        list_preferences_fn=partial(preferences_adapter.list_for_user, session),
        create_preference_fn=partial(preferences_adapter.create, session),
        list_documents_fn=partial(documents_adapter.list_for_organization, session),
        get_document_fn=partial(documents_adapter.get_for_organization, session),
        get_document_text_fn=partial(documents_adapter.get_text, session),
        get_library_fn=partial(projects_adapter.get_library, session),
        list_tree_fn=partial(projects_adapter.list_tree, session),
        create_task_fn=create_task_in_its_own_session,
        get_task_for_user_fn=partial(background_adapter.get_for_user, session),
        list_unreported_fn=partial(background_adapter.list_unreported, session),
        mark_reported_fn=partial(background_adapter.mark_reported, session),
        search_messages_fn=partial(conversations_adapter.search_messages, session),
    )


def sql_tool_context(
    session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    user_role: str,
    bucket_store: BucketStore,
    credentials: Mapping[str, Credential],
    llm_factory: LLMFactory,
    conversation_id: UUID | None = None,
    events: ToolEvents | None = None,
) -> ToolContext:
    """A run's context on the database, through `session`."""
    return ToolContext(
        organization_id=organization_id,
        user_id=user_id,
        user_role=user_role,
        bucket_store=bucket_store,
        credentials=credentials,
        llm_factory=llm_factory,
        files=project_files(session, organization_id, user_id, bucket_store),
        ports=sql_tool_ports(session),
        conversation_id=conversation_id,
        events=events,
    )
