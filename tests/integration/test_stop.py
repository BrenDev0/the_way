"""Stopping the agent's work, on a real database and a real Redis: a conversation turn, and a
background task. What was done is kept, the agent is told, and the work can carry on."""

from uuid import uuid4

import pytest
from helpers import FakeBucketStore, FakeLLM, make_completion

from src.assistants.sql import sql_tool_context
from src.background import control as background_control
from src.background import jobs as background_jobs
from src.background import paused as background_paused
from src.background import tools as background_tools
from src.background import use_cases as background_use_cases
from src.background.domain import BackgroundTaskCreate, TaskStatus
from src.background.sqlalchemy import adapter as background_adapter
from src.conversations import prompt
from src.conversations import tasks as conversation_tasks
from src.conversations.domain import (
    ConversationCreate,
    ConversationStatus,
    PauseReason,
    TurnState,
)
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.conversations.use_cases import turns as turn_use_cases
from src.core import stop as stop_signal
from src.core.exceptions import ConflictError, NotFoundError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects.sqlalchemy.store import project_files
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
async def conversation(db_session, owner):
    created = await conversations_adapter.create(
        db_session,
        ConversationCreate(organization_id=owner.organization_id, user_id=owner.id, title="First thread"),
    )
    await db_session.commit()
    return created


@pytest.fixture
def bucket():
    return FakeBucketStore()


def store_fns(db_session):
    return {
        "get_conversation_for_user_fn": lambda cid, uid: conversations_adapter.get_for_user(db_session, cid, uid),
        "save_turn_state_fn": lambda cid, turn: conversations_adapter.save_turn_state(db_session, cid, turn),
    }


async def append(db_session, cid, messages):
    return await conversations_adapter.append_messages(db_session, cid, messages)


async def send(db_session, conversation, message):
    await turn_use_cases.send_message(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        message=message,
        append_messages_fn=lambda cid, msgs: append(db_session, cid, msgs),
        **store_fns(db_session),
    )
    await db_session.commit()


async def reload(db_session, conversation):
    await db_session.rollback()
    return await conversations_adapter.get_by_id(db_session, conversation.id)


async def history(db_session, conversation):
    return await conversations_adapter.list_messages(db_session, conversation.id)


class StopsMidReply(FakeLLM):
    """Writes the start of a reply; the user presses Stop; it would have written more."""

    def __init__(self, cache, key):
        super().__init__()
        self.cache, self.key = cache, key

    async def respond(self, messages, tools=(), on_text=None):
        import asyncio

        self.received.append(list(messages))
        await on_text("Working on")
        await stop_signal.request(self.cache, self.key)
        await asyncio.sleep(0.5)  # the next word is where the worker looks
        await on_text(" the report")
        raise AssertionError("the reply must not go on after the stop")


# --- a conversation turn --------------------------------------------------------------------


async def test_a_stop_asked_before_the_agent_speaks_ends_the_turn_without_calling_the_model(
    db_session, conversation, cache
):
    await send(db_session, conversation, "build me a report")
    await stop_signal.request(cache, stop_signal.conversation_key(conversation.id))
    llm = FakeLLM("never said")

    status = await conversation_tasks.run_turn(conversation.id, llm=llm, cache=cache, run="m1")

    current = await reload(db_session, conversation)
    assert status is ConversationStatus.PAUSED
    assert current.turn.pause.reason is PauseReason.STOPPED
    assert llm.received == []
    messages = await history(db_session, conversation)
    assert messages[-1] == llm_domain.system(prompt.STOPPED_NOTE)
    # asked for once, consumed once: the next turn is not stopped by it
    assert not await stop_signal.requested(cache, stop_signal.conversation_key(conversation.id))


async def test_a_stop_while_the_agent_writes_keeps_what_it_wrote_and_tells_it_so(db_session, conversation, cache):
    await send(db_session, conversation, "build me a report")
    llm = StopsMidReply(cache, stop_signal.conversation_key(conversation.id))

    status = await conversation_tasks.run_turn(conversation.id, llm=llm, cache=cache, run="m1")

    current = await reload(db_session, conversation)
    assert status is ConversationStatus.PAUSED
    assert current.turn.pause.reason is PauseReason.STOPPED
    messages = [m for m in await history(db_session, conversation) if m["role"] != "system" or m["content"] == prompt.STOPPED_NOTE]
    assert [m["role"] for m in messages] == ["user", "assistant", "system"]
    assert messages[1]["content"].startswith("Working on the report")
    assert messages[1]["content"].endswith("[...]")


async def test_continuing_a_stopped_turn_carries_on_and_the_agent_knows_it_was_stopped_and_continued(
    db_session, conversation, cache
):
    await send(db_session, conversation, "build me a report")
    await stop_signal.request(cache, stop_signal.conversation_key(conversation.id))
    await conversation_tasks.run_turn(conversation.id, llm=FakeLLM("never"), cache=cache, run="m1")

    await turn_use_cases.resume_turn(
        conversation.id,
        conversation.user_id,
        append_messages_fn=lambda cid, msgs: append(db_session, cid, msgs),
        **store_fns(db_session),
    )
    await db_session.commit()
    llm = FakeLLM("here is the report")
    status = await conversation_tasks.run_turn(conversation.id, llm=llm, cache=cache, run="m2")

    assert status is ConversationStatus.IDLE
    told = [m["content"] for m in llm.received[0] if m["role"] == "system"]
    assert prompt.STOPPED_NOTE in told
    assert told.index(prompt.STOPPED_NOTE) < told.index(prompt.RESUMED_NOTE)  # in that order
    assert llm.received[0][-1] == llm_domain.system(prompt.RESUMED_NOTE)


async def test_a_new_message_after_a_stop_starts_a_turn_that_knows_what_happened(db_session, conversation, cache):
    await send(db_session, conversation, "build me a report")
    await stop_signal.request(cache, stop_signal.conversation_key(conversation.id))
    await conversation_tasks.run_turn(conversation.id, llm=FakeLLM("never"), cache=cache, run="m1")

    await send(db_session, conversation, "actually, make it shorter")
    llm = FakeLLM("a shorter one")
    status = await conversation_tasks.run_turn(conversation.id, llm=llm, cache=cache, run="m2")

    assert status is ConversationStatus.IDLE
    seen = llm.received[0]
    stopped_at = next(i for i, m in enumerate(seen) if m["role"] == "system" and m["content"] == prompt.STOPPED_NOTE)
    asked_at = next(i for i, m in enumerate(seen) if m.get("content") == "actually, make it shorter")
    assert stopped_at < asked_at  # it knows it was stopped before it reads what they say next


async def test_stopping_a_turn_that_waits_on_the_desktop_answers_every_call_so_the_history_stays_whole(
    db_session, conversation
):
    await send(db_session, conversation, "read the file")
    calls = (ToolCall(id="c1", name="ReadFile", args={"file_path": "a.txt"}),)
    await append(db_session, conversation.id, [llm_domain.assistant("", calls)])
    await conversations_adapter.save_turn_state(
        db_session,
        conversation.id,
        TurnState(status=ConversationStatus.AWAITING_CLIENT, pending_tool_calls=calls, iterations_used=1),
    )
    await db_session.commit()

    async def never():
        raise AssertionError("nobody is working: there is no worker to ask")

    stopped = await turn_use_cases.stop_turn(
        conversation.id,
        conversation.user_id,
        append_messages_fn=lambda cid, msgs: append(db_session, cid, msgs),
        request_stop_fn=never,
        **store_fns(db_session),
    )
    await db_session.commit()

    assert stopped.turn.status is ConversationStatus.PAUSED
    assert stopped.turn.pause.reason is PauseReason.STOPPED
    assert stopped.turn.pending_tool_calls == ()
    messages = await history(db_session, conversation)
    assert [m["role"] for m in messages[-3:]] == ["assistant", "tool", "system"]
    assert messages[-2]["tool_call_id"] == "c1"


# --- a background task -----------------------------------------------------------------------


async def make_task(db_session, owner, conversation_id=None, deliver_project=None):
    task = await background_adapter.create(
        db_session,
        BackgroundTaskCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            conversation_id=conversation_id,
            description="Quarterly report",
            instructions="Write the report",
            deliver_project=deliver_project,
        ),
    )
    await db_session.commit()
    return task


def factory_of(llm):
    async def factory(preferred=(), temperature=0.0):
        return llm

    return factory


class RaisesStopOnFirstReply(FakeLLM):
    """Its first reply asks for a tool, and the user presses Stop while it is being made."""

    def __init__(self, cache, key, *replies):
        super().__init__(*replies)
        self.cache, self.key = cache, key
        self.first = True

    async def respond(self, messages, tools=(), on_text=None):
        if self.first:
            self.first = False
            await stop_signal.request(self.cache, self.key)
        return await super().respond(messages, tools, on_text)


async def test_a_task_stopped_before_it_starts_keeps_its_place_and_says_it_was_stopped(
    db_session, owner, bucket, cache
):
    task = await make_task(db_session, owner)
    await stop_signal.request(cache, stop_signal.task_key(task.id))
    llm = FakeLLM("never")

    status = await background_jobs.run_task(task.id, bucket, llm_factory=factory_of(llm), cache=cache)

    await db_session.rollback()
    stopped = await background_adapter.get_by_id(db_session, task.id)
    assert status == TaskStatus.STOPPED
    assert stopped.status is TaskStatus.STOPPED
    assert stopped.result.startswith(background_use_cases.STOPPED_MARKER)
    assert "ResumeBackgroundTask" in stopped.result
    assert llm.received == []
    kept = await background_paused.load(cache, task.id)
    assert kept is not None and kept.stopped is True
    assert not await stop_signal.requested(cache, stop_signal.task_key(task.id))


async def test_a_task_stopped_part_way_keeps_its_files_and_carries_on_from_there(db_session, owner, bucket, cache):
    await project_files(db_session, owner.organization_id, owner.id, bucket).create_project("Reports")
    task = await make_task(db_session, owner, deliver_project="Reports")
    folder = f"tasks/{task.folder}"
    write = make_completion(
        "",
        (ToolCall(id="w1", name="WriteProjectFile", args={"project": ".the_way", "path": f"{folder}/part1.md", "content": "# One"}),),
    )
    first = RaisesStopOnFirstReply(cache, stop_signal.task_key(task.id), write, "never")

    status = await background_jobs.run_task(task.id, bucket, llm_factory=factory_of(first), cache=cache)

    await db_session.rollback()
    stopped = await background_adapter.get_by_id(db_session, task.id)
    assert status == TaskStatus.STOPPED
    assert "part1.md" in stopped.result  # what it made so far stays, and is named
    assert "nothing was delivered" in stopped.result
    assert len(first.received) == 1  # the second reply was never asked for

    # the user resumes it
    resumed = await background_control.resume(db_session, cache, task.id, owner.id)
    await db_session.commit()
    assert resumed.status is TaskStatus.RUNNING
    second = FakeLLM(
        make_completion(
            "",
            (ToolCall(id="w2", name="WriteProjectFile", args={"project": ".the_way", "path": f"{folder}/part2.md", "content": "# Two"}),),
        ),
        "Wrote part1.md and part2.md.",
    )

    status = await background_jobs.run_task(task.id, bucket, llm_factory=factory_of(second), cache=cache)

    await db_session.rollback()
    finished = await background_adapter.get_by_id(db_session, task.id)
    assert status == TaskStatus.DONE
    told = [m["content"] for m in second.received[0] if m["role"] == "user"]
    assert background_use_cases.TASK_RESUMED in told  # the worker knows it was stopped and told to go on
    # the first part's work is in what the resumed worker saw: it did not start over
    assert any(m["role"] == "tool" for m in second.received[0])
    assert await background_paused.load(cache, task.id) is None  # the kept run is used up
    assert "part1.md" in finished.result and "part2.md" in finished.result


async def test_the_conversation_is_told_a_task_was_stopped_on_its_next_turn_and_not_before(
    db_session, owner, conversation, bucket, cache
):
    task = await make_task(db_session, owner, conversation_id=conversation.id)
    await stop_signal.request(cache, stop_signal.task_key(task.id))
    await background_jobs.run_task(task.id, bucket, llm_factory=factory_of(FakeLLM("never")), cache=cache)

    await db_session.rollback()
    news = await background_adapter.list_unreported(db_session, conversation.id)

    assert [t.id for t in news] == [task.id]
    text = background_use_cases.news(news)
    assert background_use_cases.STOPPED_MARKER in text and str(task.id) in text


async def test_stopping_a_running_task_raises_the_flag_and_changes_nothing_else(db_session, owner, cache):
    task = await make_task(db_session, owner)

    returned = await background_control.stop(db_session, cache, task.id, owner.id)

    assert returned.status is TaskStatus.RUNNING
    assert await stop_signal.requested(cache, stop_signal.task_key(task.id))


async def test_a_task_waiting_on_an_approval_is_stopped_at_once_and_left_resumable(db_session, owner, cache):
    task = await make_task(db_session, owner)
    await background_adapter.set_status(db_session, task.id, TaskStatus.NEEDS_APPROVAL)
    await db_session.commit()

    stopped = await background_control.stop(db_session, cache, task.id, owner.id)
    await db_session.commit()

    assert stopped.status is TaskStatus.STOPPED
    resumed = await background_control.resume(db_session, cache, task.id, owner.id)
    assert resumed.status is TaskStatus.RUNNING


@pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.STOPPED])
async def test_only_a_running_or_waiting_task_can_be_stopped(db_session, owner, cache, status):
    task = await make_task(db_session, owner)
    await background_adapter.set_status(db_session, task.id, status)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc:
        await background_control.stop(db_session, cache, task.id, owner.id)

    assert exc.value.code == "task_not_running"


@pytest.mark.parametrize("status", [TaskStatus.RUNNING, TaskStatus.DONE, TaskStatus.NEEDS_APPROVAL])
async def test_only_a_stopped_task_can_be_resumed(db_session, owner, cache, status):
    task = await make_task(db_session, owner)
    await background_adapter.set_status(db_session, task.id, status)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc:
        await background_control.resume(db_session, cache, task.id, owner.id)

    assert exc.value.code == "task_not_stopped"


async def test_nobody_can_stop_or_resume_someone_elses_task(db_session, owner, cache):
    task = await make_task(db_session, owner)

    with pytest.raises(NotFoundError):
        await background_control.stop(db_session, cache, task.id, uuid4())
    with pytest.raises(NotFoundError):
        await background_control.resume(db_session, cache, task.id, uuid4())


async def test_resuming_makes_the_tasks_end_news_again(db_session, owner, conversation, cache):
    task = await make_task(db_session, owner, conversation_id=conversation.id)
    await background_adapter.finish(db_session, task.id, TaskStatus.STOPPED, "stopped")
    await background_adapter.mark_reported(db_session, [task.id])
    await db_session.commit()

    await background_control.resume(db_session, cache, task.id, owner.id)
    await db_session.commit()
    await background_adapter.finish(db_session, task.id, TaskStatus.DONE, "all done")
    await db_session.commit()

    assert [t.id for t in await background_adapter.list_unreported(db_session, conversation.id)] == [task.id]


# --- the agent's own tools ----------------------------------------------------------------------


def context_with_cache(db_session, owner, bucket, cache, conversation_id=None):
    async def refuse(preferred=(), temperature=0.0):
        raise AssertionError("this test builds no model")

    return sql_tool_context(
        db_session,
        organization_id=owner.organization_id,
        user_id=owner.id,
        user_role=str(owner.role),
        bucket_store=bucket,
        credentials={},
        llm_factory=refuse,
        conversation_id=conversation_id,
        cache=cache,
    )


async def test_the_agent_can_stop_a_task_on_request_and_is_not_told_about_it_again(
    db_session, owner, conversation, bucket, cache
):
    task = await make_task(db_session, owner, conversation_id=conversation.id)
    tools = background_tools.build(context_with_cache(db_session, owner, bucket, cache, conversation.id))

    reply = await tools["StopBackgroundTask"].handler(task_id=str(task.id))

    assert "Stop requested" in reply and "Do not say it has stopped yet" in reply
    assert await stop_signal.requested(cache, stop_signal.task_key(task.id))
    # the worker stops it a moment later; the user asked in the conversation, so it is not news
    await background_adapter.finish(db_session, task.id, TaskStatus.STOPPED, "stopped")
    await db_session.commit()
    assert await background_adapter.list_unreported(db_session, conversation.id) == []


async def test_the_agent_can_resume_a_stopped_task_and_it_is_committed_before_it_is_enqueued(
    db_session, owner, bucket, cache
):
    task = await make_task(db_session, owner)
    await background_adapter.finish(db_session, task.id, TaskStatus.STOPPED, "stopped")
    await db_session.commit()
    enqueued = []

    async def enqueue(task_id):
        # the worker looks for a running task: it must already be one when it is sent
        await db_session.rollback()
        seen = await background_adapter.get_by_id(db_session, task_id)
        enqueued.append(seen.status)

    tools = background_tools.build(context_with_cache(db_session, owner, bucket, cache), enqueue=enqueue)

    reply = await tools["ResumeBackgroundTask"].handler(task_id=str(task.id))

    assert enqueued == [TaskStatus.RUNNING]
    assert "running again" in reply


async def test_the_agent_is_told_plainly_when_a_task_cannot_be_stopped_or_resumed(db_session, owner, bucket, cache):
    task = await make_task(db_session, owner)
    await background_adapter.finish(db_session, task.id, TaskStatus.DONE, "done")
    await db_session.commit()
    tools = background_tools.build(context_with_cache(db_session, owner, bucket, cache))

    assert "Not stopped" in await tools["StopBackgroundTask"].handler(task_id=str(task.id))
    assert "Not resumed" in await tools["ResumeBackgroundTask"].handler(task_id=str(task.id))
    assert "not found" in await tools["StopBackgroundTask"].handler(task_id="not-an-id")
