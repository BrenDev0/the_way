import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from helpers import FakeBucketStore, FakeLLM, make_completion

from src.background import jobs as background_jobs
from src.background import tools as background_tools
from src.background.domain import BackgroundTaskCreate, TaskStatus
from src.background.sqlalchemy import adapter as background_adapter
from src.conversations import events as conversation_events
from src.conversations import tasks as conversation_tasks
from src.conversations import tools as conversation_tools
from src.conversations import use_cases as conversations_use_cases
from src.conversations.domain import (
    ConversationCreate,
    ConversationStatus,
    ToolResolution,
)
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.events.memory import InMemoryEventStream
from src.core.llm.domain import ToolCall
from src.core.tools.context import ToolContext
from src.core.tools.domain import ToolLocation
from src.crm import datasets
from src.crm import query as crm_query
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.preferences import tools as preference_tools
from src.projects import tools as project_tools
from src.projects.files import ProjectFiles
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


@pytest.fixture
async def owner(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme"))
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )
    await db_session.commit()
    return user


@pytest.fixture
def bucket():
    return FakeBucketStore()


def context_for(db_session, user, bucket, llm_factory=None, conversation_id=None):
    async def refuse(preferred=(), temperature=0.0):
        raise AssertionError("this test builds no model")

    return ToolContext(
        session=db_session,
        organization_id=user.organization_id,
        user_id=user.id,
        user_role=str(user.role),
        bucket_store=bucket,
        credentials={},
        llm_factory=llm_factory or refuse,
        conversation_id=conversation_id,
    )


async def run(tools, tool, **args):
    return await tools[tool].handler(**args)


# --- project file tools ----------------------------------------------------------------


async def test_a_file_written_by_path_reads_back(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")

    await run(tools, "WriteProjectFile", project="website", path="docs/notes/plan.md", content="# Plan\r\nShip it")

    assert await run(tools, "ReadProjectFile", project="Website", path="docs/notes/plan.md") == "# Plan\nShip it"
    assert await run(tools, "ListProjectFolder", project="Website", path="docs") == "notes/"


async def test_writing_over_a_file_needs_overwrite(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")
    await run(tools, "WriteProjectFile", project="Website", path="a.md", content="one")

    with pytest.raises(Exception) as exc:
        await run(tools, "WriteProjectFile", project="Website", path="A.md", content="two")

    assert getattr(exc.value, "code", "") == "project_entry_name_taken"
    await run(tools, "WriteProjectFile", project="Website", path="a.md", content="two", overwrite=True)
    assert await run(tools, "ReadProjectFile", project="Website", path="a.md") == "two"


async def test_an_edit_replaces_exactly_one_occurrence(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")
    await run(tools, "WriteProjectFile", project="Website", path="a.css", content="a{} b{}")

    await run(tools, "EditProjectFile", project="Website", path="a.css", old_string="b{}", new_string="b{color:red}")

    assert await run(tools, "ReadProjectFile", project="Website", path="a.css") == "a{} b{color:red}"


async def test_find_matches_words_across_the_path(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")
    await run(tools, "WriteProjectFile", project="Website", path="progreso/q3/report.md", content="x")

    found = await run(tools, "FindProjectFiles", project="Website", query="progreso report")

    assert found == "progreso/q3/report.md"


async def test_copy_into_another_project_keeps_the_original(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Source")
    await run(tools, "CreateProject", name="Target")
    await run(tools, "WriteProjectFile", project="Source", path="kit/a.txt", content="alpha")
    await run(tools, "WriteProjectFile", project="Source", path="kit/deep/b.txt", content="beta")
    await run(tools, "CreateProjectFolder", project="Target", path="incoming")

    result = await run(
        tools, "CopyProjectPath",
        source_project="Source", source_path="kit",
        destination_project="Target", destination_path="incoming",
    )

    assert "Copied 2 file(s)" in result
    assert await run(tools, "ReadProjectFile", project="Target", path="incoming/kit/deep/b.txt") == "beta"
    assert await run(tools, "ReadProjectFile", project="Source", path="kit/a.txt") == "alpha"


async def test_move_renames_and_relocates(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")
    await run(tools, "WriteProjectFile", project="Website", path="draft.md", content="text")

    await run(tools, "MoveProjectPath", project="Website", source_path="draft.md", destination_path="final/post.md")

    assert await run(tools, "ReadProjectFile", project="Website", path="final/post.md") == "text"
    assert "draft.md" not in await run(tools, "ListProjectFolder", project="Website")


async def test_delete_removes_the_folder_and_its_objects(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))
    await run(tools, "CreateProject", name="Website")
    await run(tools, "WriteProjectFile", project="Website", path="old/a.md", content="x")

    await run(tools, "DeleteProjectPath", project="Website", path="old")

    assert await run(tools, "ListProjectFolder", project="Website") == "(empty folder)"
    assert len(bucket.deleted) == 1


async def test_the_workspace_appears_the_first_time_it_is_used(db_session, owner, bucket):
    tools = project_tools.build(context_for(db_session, owner, bucket))

    await run(tools, "WriteProjectFile", project=".the_way", path="design/brand.md", content="Inter")

    assert ".the_way" in await run(tools, "ListProjects")


async def test_someone_elses_project_is_not_reachable_by_name(db_session, owner, bucket):
    colleague = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=owner.organization_id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.MEMBER,
        ),
    )
    await run(project_tools.build(context_for(db_session, owner, bucket)), "CreateProject", name="Secret")

    with pytest.raises(Exception) as exc:
        await run(
            project_tools.build(context_for(db_session, colleague, bucket)),
            "ListProjectFolder",
            project="Secret",
        )

    assert getattr(exc.value, "code", "") == "project_not_found"


# --- preferences -----------------------------------------------------------------------


async def test_a_remembered_preference_reaches_the_turn_context(db_session, owner, bucket):
    context = context_for(db_session, owner, bucket)

    await preference_tools.build(context)["RememberPreference"].handler(preference="Answer in Spanish")

    assert "- Answer in Spanish" in await preference_tools.context_block(context)


# --- background tasks ------------------------------------------------------------------


async def test_a_background_task_writes_verifies_and_delivers(db_session, owner, bucket):
    await ProjectFiles(db_session, owner.organization_id, owner.id, bucket).create_project("Reports")
    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=None,
            description="Quarterly report",
            instructions="Write the report",
            deliver_project="Reports",
            deliver_path="q3",
        ),
    )
    await db_session.commit()
    folder = f"tasks/{task.folder}"

    worker = FakeLLM(
        make_completion(
            "",
            (
                ToolCall(
                    id="w1",
                    name="WriteProjectFile",
                    # the worker wraps its output in a folder named after the destination
                    args={"project": ".the_way", "path": f"{folder}/q3/report.md", "content": "# Q3"},
                ),
            ),
        ),
        "Wrote q3/report.md with the quarterly summary.",
    )

    async def factory(preferred=(), temperature=0.0):
        return worker

    status = await background_jobs.run_task(task.id, bucket, llm_factory=factory)

    await db_session.rollback()
    finished = await background_adapter.get_by_id(db_session, task.id)
    assert status == TaskStatus.DONE
    assert "q3/report.md" in finished.result
    assert "dropped the redundant q3/" in finished.result

    files = ProjectFiles(db_session, owner.organization_id, owner.id, bucket)
    _, data = await files.read_bytes(await files.project("Reports"), "q3/report.md")
    assert data == b"# Q3"


async def test_a_background_task_reports_its_work_on_the_conversation_that_started_it(
    db_session, owner, bucket
):
    conversation = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="Desk")
    )
    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=conversation.id,
            description="Inventory",
            instructions="List the projects",
        ),
    )
    await db_session.commit()

    async def factory(preferred=(), temperature=0.0):
        return FakeLLM(make_completion("", (ToolCall(id="l1", name="ListProjects", args={}),)), "Done.")

    stream = InMemoryEventStream()
    await background_jobs.run_task(task.id, bucket, llm_factory=factory, event_stream=stream)

    published = stream.of(conversation_events.topic(conversation.id))
    assert [event.type for event in published] == ["task.started", "tool.started", "tool.finished", "task.finished"]
    assert published[0].data == {"taskId": str(task.id), "description": "Inventory"}
    assert published[1].data["taskId"] == str(task.id)
    assert published[1].data["name"] == "ListProjects"
    assert published[-1].data["status"] == str(TaskStatus.DONE)


async def test_a_worker_out_of_steps_is_failed_and_not_delivered(db_session, owner, bucket):
    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=None,
            description="Endless",
            instructions="Loop",
            deliver_project="Nowhere",
        ),
    )
    await db_session.commit()
    loops = [
        make_completion("", (ToolCall(id=f"l{i}", name="ListProjects", args={}),))
        for i in range(background_jobs.config.MAX_ITERATIONS)
    ]

    async def factory(preferred=(), temperature=0.0):
        return FakeLLM(*loops, "I only listed projects.")

    status = await background_jobs.run_task(task.id, bucket, llm_factory=factory)

    await db_session.rollback()
    finished = await background_adapter.get_by_id(db_session, task.id)
    assert status == TaskStatus.FAILED
    assert finished.result.startswith("TASK FAILED")
    assert "NO FILES were written" in finished.result


async def test_starting_a_task_commits_it_before_enqueueing(db_session, owner, bucket):
    enqueued = []

    async def enqueue(task_id):
        enqueued.append(task_id)

    tools = background_tools.build(context_for(db_session, owner, bucket), enqueue=enqueue)
    reply = await tools["StartBackgroundTask"].handler(description="Audit", instructions="Audit it")

    assert len(enqueued) == 1
    assert "No delivery folder was set" in reply
    await db_session.rollback()
    assert (await background_adapter.get_by_id(db_session, enqueued[0])).status is TaskStatus.RUNNING


# --- CX datasets ----------------------------------------------------------------------


class FakeCX:
    """A CX sub-account over MCP: one searchAfter-paged operation holding 250 contacts."""

    location_id = "loc-1"

    def __init__(self):
        self.calls = 0
        self.rows = [
            {"id": f"c{n}", "stage": "won" if n % 5 == 0 else "open", "searchAfter": [n]}
            for n in range(250)
        ]

    @asynccontextmanager
    async def session(self):
        yield object()

    async def describe(self, operation_id, client=None):
        return json.dumps(
            {
                "operation": {
                    "kind": "read",
                    "hasRequestBody": True,
                    "requestBodyFields": [{"name": "pageLimit"}, {"name": "searchAfter"}],
                    "parameterNames": [],
                }
            }
        )

    async def execute(self, operation_id, params=None, dry_run=False, reason="", idempotency_key=None, client=None):
        self.calls += 1
        body = params["body"]
        start = body.get("searchAfter", [-1])[0] + 1
        page = self.rows[start : start + body["pageLimit"]]
        return json.dumps({"success": True, "data": {"contacts": page, "total": len(self.rows)}})


async def test_a_dataset_pages_to_the_end_and_counts_exactly(db_session, owner, bucket):
    files = ProjectFiles(db_session, owner.organization_id, owner.id, bucket)
    cx = FakeCX()

    report = await datasets.fetch(cx, files, "contacts", "search-contacts-advanced")

    assert "250 rows of 250 reported by CX" in report
    assert "Complete: yes" in report
    rows = await files.read_json_lines(
        await files.workspace(), f"data/contacts-{datasets.today()}/rows.ndjson"
    )
    assert crm_query.run(rows, [{"field": "stage", "op": "eq", "value": "won"}]).startswith("50 of 250")


async def test_a_second_ask_is_served_from_the_day_cache(db_session, owner, bucket):
    files = ProjectFiles(db_session, owner.organization_id, owner.id, bucket)
    cx = FakeCX()
    await datasets.fetch(cx, files, "contacts", "search-contacts-advanced")
    calls = cx.calls

    again = await datasets.fetch(cx, files, "all-contacts", "search-contacts-advanced")

    assert cx.calls == calls
    assert "no API calls were made" in again


async def test_a_write_operation_is_refused(db_session, owner, bucket):
    class WritingCX(FakeCX):
        async def describe(self, operation_id, client=None):
            return json.dumps({"operation": {"kind": "delete"}})

    report = await datasets.fetch(
        WritingCX(), ProjectFiles(db_session, owner.organization_id, owner.id, bucket), "x", "delete-contact"
    )

    assert report.startswith("Refusing to fetch")


# --- history and the desktop round trip -------------------------------------------------


async def test_history_search_finds_an_earlier_conversation(db_session, owner, bucket):
    earlier = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="Old")
    )
    await conversations_adapter.append_messages(
        db_session,
        earlier.id,
        [{"role": "user", "content": "Build the progreso landing page, price 49 dollars"}],
    )
    await db_session.commit()

    tools = conversation_tools.build(context_for(db_session, owner, bucket), desktop=False)
    found = await tools["SearchConversationHistory"].handler(query="progreso price")

    assert "progreso landing page" in found


async def test_a_desktop_call_pauses_the_turn_and_resumes_with_its_output(db_session, owner):
    conversation = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="Desk")
    )
    await db_session.commit()

    async def get(cid, uid):
        return await conversations_adapter.get_for_user(db_session, cid, uid)

    async def append(cid, msgs):
        return await conversations_adapter.append_messages(db_session, cid, msgs)

    async def save(cid, turn):
        return await conversations_adapter.save_turn_state(db_session, cid, turn)

    await conversations_use_cases.send_message(conversation.id, owner.id, "what is in notes.txt?", get, append, save)
    await db_session.commit()

    read = ToolCall(id="read-1", name="ReadFile", args={"file_path": "notes.txt"})
    llm = FakeLLM(make_completion("", (read,)), "The notes say: buy milk.")

    status = await conversation_tasks.run_turn(conversation.id, llm=llm)

    await db_session.rollback()
    paused = await conversations_adapter.get_by_id(db_session, conversation.id)
    assert status is ConversationStatus.AWAITING_CLIENT
    assert paused.turn.pending_requests[0].location is ToolLocation.DESKTOP
    assert paused.turn.pending_requests[0].call.args == {"file_path": "notes.txt"}

    await conversations_use_cases.resolve_tool_calls(
        conversation.id,
        owner.id,
        [ToolResolution("read-1", approved=True, output="buy milk")],
        get,
        save,
    )
    await db_session.commit()

    status = await conversation_tasks.run_turn(conversation.id, llm=llm)

    await db_session.rollback()
    done = await conversations_adapter.get_by_id(db_session, conversation.id)
    messages = await conversations_adapter.list_messages(db_session, conversation.id)
    assert status is ConversationStatus.IDLE
    assert done.turn.decisions == {}
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[2]["content"] == "buy milk"
    assert messages[3]["content"] == "The notes say: buy milk."
