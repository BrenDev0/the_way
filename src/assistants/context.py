from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from src.background.ports import (
    CreateTaskFn,
    GetTaskForUserFn,
    ListUnreportedFn,
    MarkReportedFn,
    ResumeTaskFn,
    StopTaskFn,
)
from src.conversations.ports import SearchMessagesFn
from src.core.bucket.ports import BucketStore
from src.core.llm.ports import LLM
from src.core.tools.ports import ToolEvents
from src.documents.ports import (
    GetDocumentFn,
    GetDocumentTextFn,
    ListDocumentsForOrganizationFn,
)
from src.preferences.ports import CreatePreferenceFn, ListPreferencesForUserFn
from src.projects.files import ProjectFiles
from src.projects.ports import GetLibraryFn, ListTreeFn
from src.skills.ports import (
    CountSkillsFn,
    GetSkillFn,
    ListSkillsForOrganizationFn,
    UpsertSkillFn,
)


class LLMFactory(Protocol):
    """A model built from the user's own keys: the first of `preferred` whose provider
    they hold a key for, otherwise their default model."""

    async def __call__(
        self, preferred: Sequence[str] = (), temperature: float = 0.0
    ) -> LLM: ...


@dataclass(frozen=True)
class Credential:
    secret: str
    account_id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ToolPorts:
    """What the tools read and write besides project files, as ports.

    The run's composition root binds each to the database (assistants/sql.py); a test
    binds them to fakes. A tool never sees a session."""

    # skills
    list_skills_fn: ListSkillsForOrganizationFn
    get_skill_fn: GetSkillFn
    count_skills_fn: CountSkillsFn
    upsert_skill_fn: UpsertSkillFn
    # what the user asked to have remembered
    list_preferences_fn: ListPreferencesForUserFn
    create_preference_fn: CreatePreferenceFn
    # the knowledge index: documents, and the library's tree
    list_documents_fn: ListDocumentsForOrganizationFn
    get_document_fn: GetDocumentFn
    get_document_text_fn: GetDocumentTextFn
    get_library_fn: GetLibraryFn
    list_tree_fn: ListTreeFn
    # background tasks; create_task_fn commits on its own, apart from the turn's transaction
    create_task_fn: CreateTaskFn
    get_task_for_user_fn: GetTaskForUserFn
    list_unreported_fn: ListUnreportedFn
    mark_reported_fn: MarkReportedFn
    # the user's own past messages
    search_messages_fn: SearchMessagesFn
    # stopping and resuming the user's background tasks; unset where there is no cache to ask
    # a worker through, and the tools for it are then not offered
    stop_task_fn: StopTaskFn | None = None
    resume_task_fn: ResumeTaskFn | None = None


@dataclass(frozen=True)
class ToolContext:
    """Everything a slice needs to build its tools for one run, on behalf of one user.

    Tools are built fresh per run and close over this, so every call is scoped to the
    user the run belongs to -- a tool can never be pointed at someone else's data."""

    organization_id: UUID
    user_id: UUID
    user_role: str
    bucket_store: BucketStore
    credentials: Mapping[str, Credential]
    llm_factory: LLMFactory
    # this user's project file system, and the ports the other tools use
    files: ProjectFiles
    ports: ToolPorts
    conversation_id: UUID | None = None
    # Where a tool that runs an assistant of its own reports that assistant's tool calls,
    # so whoever watches the run sees the work instead of one long silent call.
    events: ToolEvents | None = None
