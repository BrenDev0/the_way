"""A skill reaches every agent that does the work -- the worker, the page builder -- and
its reads are counted from what was stored."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from helpers import FakeBucketStore, FakeLLM

from src.assistants.sql import sql_tool_context
from src.background import jobs as background_jobs
from src.background import tools as background_tools
from src.background.domain import BackgroundTaskCreate
from src.background.sqlalchemy import adapter as background_adapter
from src.conversations.domain import ConversationCreate
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.html_pages import tools as html_tools
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.skills import usage
from src.skills.domain import SkillCreate
from src.skills.sqlalchemy import adapter as skills_adapter
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
    await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="landing-pages",
            description="Build a landing page that is true and works on the phone.",
            instructions="0 Brief, 1 Structure, 2 Copy.",
            triggers=["build a landing page for <client>"],
            files={"laws.md": "# Laws\nEvery figure attributed.", "engine/run.js": "process.exit()"},
        ),
    )
    await db_session.commit()
    return user


def context_for(db_session, user, llm=None):
    async def factory(preferred=(), temperature=0.0):
        if llm is None:
            raise AssertionError("this test builds no model")
        return llm

    return sql_tool_context(
        db_session, organization_id=user.organization_id,
        user_id=user.id,
        user_role=str(user.role),
        bucket_store=FakeBucketStore(),
        credentials={},
        llm_factory=factory,
    )


async def enqueue_into(enqueued):
    async def enqueue(task_id):
        enqueued.append(task_id)

    return enqueue


# --- the background worker -------------------------------------------------------------


async def test_the_worker_is_shown_the_skill_listing(db_session, owner):
    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=None,
            description="Landing",
            instructions="Build the landing page",
        ),
    )
    await db_session.commit()
    worker = FakeLLM("RESULT: INCOMPLETE -- nothing to do in a test")

    async def factory(preferred=(), temperature=0.0):
        return worker

    await background_jobs.run_task(task.id, FakeBucketStore(), llm_factory=factory)

    systems = [message["content"] for message in worker.received[0] if message["role"] == "system"]
    assert any("- landing-pages: Build a landing page" in text for text in systems)


async def test_a_task_started_with_skills_tells_the_worker_to_follow_them(db_session, owner):
    enqueued: list = []
    tools = background_tools.build(context_for(db_session, owner), enqueue=await enqueue_into(enqueued))

    await tools["StartBackgroundTask"].handler(
        description="Landing", instructions="Build the SLS page.", skills=["landing-pages"]
    )

    await db_session.rollback()
    task = await background_adapter.get_by_id(db_session, enqueued[0])
    assert task.instructions.startswith("SKILLS TO FOLLOW.")
    assert "- landing-pages" in task.instructions
    assert task.instructions.endswith("Build the SLS page.")


async def test_a_task_naming_a_skill_that_is_not_there_is_not_started(db_session, owner):
    enqueued: list = []
    tools = background_tools.build(context_for(db_session, owner), enqueue=await enqueue_into(enqueued))

    reply = await tools["StartBackgroundTask"].handler(
        description="Landing", instructions="Build it.", skills=["landing-page"]
    )

    assert reply.startswith("No task was started")
    assert "Its skills: landing-pages." in reply
    assert enqueued == []


# --- the page builder ------------------------------------------------------------------


async def test_a_page_built_under_a_skill_hands_both_passes_the_skill(db_session, owner):
    llm = FakeLLM("Design brief.", "Built.")
    build = html_tools.build(context_for(db_session, owner, llm))["BuildHtmlPage"].handler

    await build(
        project="Borradores",
        output_path="p.html",
        page_type="landing",
        brief="A page.",
        skill="landing-pages",
    )

    for received in llm.received:
        request = received[-1]["content"]
        assert "=== SKILL: landing-pages" in request
        assert "0 Brief, 1 Structure, 2 Copy." in request
        assert "Every figure attributed." in request
        assert "process.exit()" not in request


async def test_a_page_naming_a_skill_that_is_not_there_builds_nothing(db_session, owner):
    llm = FakeLLM()
    build = html_tools.build(context_for(db_session, owner, llm))["BuildHtmlPage"].handler

    result = await build(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", skill="landing"
    )

    assert result.startswith("No page was built")
    assert "Its skills: landing-pages." in result
    assert llm.received == []


# --- counting the reads ----------------------------------------------------------------


async def test_reads_are_counted_from_the_stored_conversations(db_session, owner):
    read = ToolCall(id="r1", name="ReadSkill", args={"name": "landing-pages"})
    handed = ToolCall(id="b1", name="BuildHtmlPage", args={"brief": "...", "skill": "landing-pages"})
    landing = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="Landing")
    )
    await conversations_adapter.append_messages(
        db_session,
        landing.id,
        [
            llm_domain.user("hazme una landing para SLS"),
            llm_domain.assistant("", (read,)),
            llm_domain.tool_result("r1", "0 Brief..."),
            llm_domain.assistant("", (handed,)),
            llm_domain.tool_result("b1", "Wrote it."),
        ],
    )
    greeting = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="Hola")
    )
    await conversations_adapter.append_messages(db_session, greeting.id, [llm_domain.user("hola")])
    await db_session.commit()

    measured = await usage.measure(db_session, owner.organization_id, datetime.now(UTC) - timedelta(days=1))

    assert measured.conversations == 2
    assert measured.conversations_reading == 1
    assert measured.skills["landing-pages"].reads == 1
    assert measured.skills["landing-pages"].handed_on == 1


# --- what a worker did is kept -----------------------------------------------------------


async def test_a_workers_own_calls_are_kept_and_counted(db_session, owner):
    from helpers import make_completion

    from src.background.sqlalchemy.models import BackgroundTaskRow

    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=None,
            description="Landing",
            instructions="Build the landing page",
        ),
    )
    await db_session.commit()
    worker = FakeLLM(
        make_completion("", (ToolCall(id="r", name="ReadSkill", args={"name": "landing-pages"}),)),
        "RESULT: INCOMPLETE -- a test",
    )

    async def factory(preferred=(), temperature=0.0):
        return worker

    await background_jobs.run_task(task.id, FakeBucketStore(), llm_factory=factory)

    await db_session.rollback()
    row = await db_session.get(BackgroundTaskRow, task.id)
    assert [call["name"] for call in row.tool_calls] == ["ReadSkill"]
    assert row.tool_calls[0]["args"] == {"name": "landing-pages"}

    measured = await usage.measure(db_session, owner.organization_id, datetime.now(UTC) - timedelta(days=1))
    assert measured.skills["landing-pages"].worker_reads == 1
    assert measured.tasks_reading == 1


# --- transcripts -------------------------------------------------------------------------


async def test_a_recording_in_a_project_is_transcribed_and_kept(db_session, owner, monkeypatch):
    from src.api_keys.domain import Provider
    from src.assistants.context import Credential
    from src.projects.sqlalchemy.store import project_files
    from src.transcripts import fetch
    from src.transcripts import tools as transcript_tools

    sent = {}

    async def transcribe(data, filename, api_key, language):
        sent.update(data=data, filename=filename, api_key=api_key)
        return "Hola, bienvenidos a la reunión."

    monkeypatch.setattr(fetch, "transcribe", transcribe)
    bucket = FakeBucketStore()
    files = project_files(db_session, owner.organization_id, owner.id, bucket)
    project = await files.create_project("Reuniones")
    await files.write(project, "lunes/nota.m4a", b"audio-bytes", content_type="audio/mp4")
    await db_session.commit()
    context = sql_tool_context(
        db_session, organization_id=owner.organization_id, user_id=owner.id, user_role=str(owner.role),
        bucket_store=bucket, credentials={str(Provider.OPENAI): Credential(secret="sk-test")},
        llm_factory=None,  # type: ignore[arg-type]
    )

    reply = await transcript_tools.build(context)["TranscribeMedia"].handler(source="project:Reuniones/lunes/nota.m4a")

    assert sent == {"data": b"audio-bytes", "filename": "nota.m4a", "api_key": "sk-test"}
    assert "Hola, bienvenidos a la reunión." in reply
    saved = reply.split("saved as .the_way/")[1].split(" ")[0]
    _, kept = await files.read_bytes(await files.workspace(), saved)
    assert kept.decode().endswith("Hola, bienvenidos a la reunión.")


async def test_a_link_to_anywhere_else_is_not_fetched(db_session, owner):
    from src.transcripts import tools as transcript_tools

    context = context_for(db_session, owner)

    reply = await transcript_tools.build(context)["TranscribeMedia"].handler(source="http://10.0.0.5/internal.mp4")

    assert reply.startswith("'http://10.0.0.5/internal.mp4' is not a link this can fetch from")
