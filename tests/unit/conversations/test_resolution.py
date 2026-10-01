from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.conversations import use_cases
from src.conversations.domain import (
    Conversation,
    ConversationStatus,
    ToolResolution,
    TurnState,
)
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import ClientRequest, Tool, ToolLocation
from src.core.tools.executor import Executor
from src.core.tools.gates import SuspendGate


class ReadFile(BaseModel):
    file_path: str


class DeleteProjectPath(BaseModel):
    project: str
    path: str


deleted: list[str] = []


async def delete_project_path(project: str, path: str) -> str:
    deleted.append(path)
    return f"Deleted {project}/{path}"


TOOLS = {
    "ReadFile": Tool(schema=ReadFile, location=ToolLocation.DESKTOP),
    "DeleteProjectPath": Tool(
        schema=DeleteProjectPath, handler=delete_project_path, requires_approval=True
    ),
}

READ = ToolCall(id="read", name="ReadFile", args={"file_path": "a.txt"})
DELETE = ToolCall(id="delete", name="DeleteProjectPath", args={"project": "Site", "path": "x"})


def paused(*calls: ToolCall) -> TurnState:
    requests = tuple(
        ClientRequest(
            call=c,
            location=TOOLS[c.name].location,
            requires_approval=TOOLS[c.name].requires_approval,
        )
        for c in calls
    )
    return TurnState(
        status=ConversationStatus.AWAITING_CLIENT,
        pending_tool_calls=calls,
        pending_requests=requests,
        iterations_used=1,
    )


class Store:
    def __init__(self, turn: TurnState, history=()):
        now = datetime.now(UTC)
        self.conversation = Conversation(
            id=uuid4(),
            organization_id=uuid4(),
            user_id=uuid4(),
            title="Thread",
            turn=turn,
            created_at=now,
            updated_at=now,
        )
        self.messages = list(history)

    async def get_for_user(self, conversation_id, user_id):
        return self.conversation if user_id == self.conversation.user_id else None

    async def get_by_id(self, conversation_id):
        return self.conversation

    async def list_messages(self, conversation_id):
        return list(self.messages)

    async def append(self, conversation_id, messages):
        self.messages.extend(messages)
        return len(messages)

    async def save(self, conversation_id, turn):
        self.conversation.turn = turn
        return self.conversation


async def resolve(store: Store, *resolutions: ToolResolution, user_id=None):
    return await use_cases.resolve_tool_calls(
        store.conversation.id,
        user_id or store.conversation.user_id,
        list(resolutions),
        store.get_for_user,
        store.save,
    )


async def test_resolving_sets_the_turn_running_with_the_answers():
    store = Store(paused(READ))

    conversation = await resolve(store, ToolResolution("read", approved=True, output="hi"))

    assert conversation.turn.status is ConversationStatus.RUNNING
    assert conversation.turn.decisions["read"].output == "hi"
    assert conversation.turn.pending_tool_calls == (READ,)


async def test_every_pending_call_must_be_answered_together():
    store = Store(paused(READ, DELETE))

    with pytest.raises(ValidationError) as exc:
        await resolve(store, ToolResolution("read", approved=True, output="hi"))

    assert exc.value.code == "tool_calls_unresolved"
    assert "delete" in exc.value.message


async def test_approving_a_desktop_call_needs_its_output():
    store = Store(paused(READ))

    with pytest.raises(ValidationError) as exc:
        await resolve(store, ToolResolution("read", approved=True))

    assert exc.value.code == "tool_call_output_required"


async def test_a_server_call_takes_no_output():
    store = Store(paused(DELETE))

    with pytest.raises(ValidationError) as exc:
        await resolve(store, ToolResolution("delete", approved=True, output="done"))

    assert exc.value.code == "tool_call_output_not_expected"


async def test_a_desktop_call_can_be_refused_without_output():
    store = Store(paused(READ))

    conversation = await resolve(store, ToolResolution("read", approved=False, feedback="no"))

    assert conversation.turn.decisions["read"].approved is False


async def test_an_unknown_call_id_is_refused():
    store = Store(paused(READ))

    with pytest.raises(ValidationError) as exc:
        await resolve(
            store,
            ToolResolution("read", approved=True, output="hi"),
            ToolResolution("other", approved=True),
        )

    assert exc.value.code == "tool_call_not_pending"


async def test_a_call_resolved_twice_is_refused():
    store = Store(paused(READ))

    with pytest.raises(ValidationError) as exc:
        await resolve(
            store,
            ToolResolution("read", approved=True, output="a"),
            ToolResolution("read", approved=True, output="b"),
        )

    assert exc.value.code == "tool_call_resolved_twice"


async def test_a_conversation_that_is_not_paused_cannot_be_resolved():
    store = Store(TurnState(status=ConversationStatus.IDLE))

    with pytest.raises(ConflictError) as exc:
        await resolve(store)

    assert exc.value.code == "conversation_not_awaiting_client"


async def test_someone_elses_conversation_is_not_found():
    store = Store(paused(READ))

    with pytest.raises(NotFoundError):
        await resolve(store, ToolResolution("read", approved=True, output="hi"), user_id=uuid4())


async def test_the_resumed_turn_hands_the_desktop_output_to_the_model():
    store = Store(paused(READ), history=[llm_domain.user("read a.txt")])
    await resolve(store, ToolResolution("read", approved=True, output="hello from disk"))
    llm = FakeLLM("The file says hello.")

    status = await use_cases.advance_turn(
        store.conversation.id,
        llm,
        Executor(TOOLS, SuspendGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert status is ConversationStatus.IDLE
    assert {"role": "tool", "content": "hello from disk", "tool_call_id": "read"} in llm.received[0]
    assert store.conversation.turn.decisions == {}
    assert store.conversation.turn.pending_requests == ()


async def test_an_approved_server_call_runs_on_resume():
    deleted.clear()
    store = Store(paused(DELETE), history=[llm_domain.user("delete x")])
    await resolve(store, ToolResolution("delete", approved=True))

    await use_cases.advance_turn(
        store.conversation.id,
        FakeLLM("Deleted."),
        Executor(TOOLS, SuspendGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert deleted == ["x"]


async def test_a_background_notice_is_relayed_once_and_kept_as_relayed():
    store = Store(
        TurnState(status=ConversationStatus.RUNNING), history=[llm_domain.user("any news?")]
    )
    llm = FakeLLM("Your audit finished.")

    async def drain(conversation):
        return "[t1] audit -- done: Files in .the_way/tasks/audit/: report.md."

    await use_cases.advance_turn(
        store.conversation.id,
        llm,
        Executor(TOOLS, SuspendGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
        drain_notices_fn=drain,
    )

    sent_systems = [m["content"] for m in llm.received[0] if m["role"] == "system"]
    assert any("Report it in THIS reply" in text for text in sent_systems)
    kept = [m["content"] for m in store.messages if m["role"] == "system"]
    assert len(kept) == 1 and kept[0].startswith("[already reported")


async def test_a_turn_the_server_opened_to_report_a_task_starts_from_the_notice():
    # the history ends on the assistant's own reply: nobody has written since
    store = Store(
        TurnState(status=ConversationStatus.RUNNING),
        history=[llm_domain.user("haz el informe"), llm_domain.assistant("Lo inicié en segundo plano.")],
    )
    llm = FakeLLM("Tu informe está listo en Borradores.")

    async def drain(conversation):
        return "[t1] informe -- done: Files in .the_way/tasks/informe/: index.html."

    await use_cases.advance_turn(
        store.conversation.id,
        llm,
        Executor(TOOLS, SuspendGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
        drain_notices_fn=drain,
    )

    opening = llm.received[0][-1]
    assert opening["role"] == "user" and "Automatic message from the system" in opening["content"]
    # what is kept is the record of it, and the reply -- never words put in the user's mouth
    assert [m["role"] for m in store.messages[2:]] == ["system", "assistant"]


async def test_a_turn_pausing_on_a_desktop_call_waits_for_the_client():
    store = Store(TurnState(status=ConversationStatus.RUNNING), history=[llm_domain.user("hi")])

    status = await use_cases.advance_turn(
        store.conversation.id,
        FakeLLM(make_completion("", (READ,))),
        Executor(TOOLS, SuspendGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert status is ConversationStatus.AWAITING_CLIENT
    assert store.conversation.turn.pending_requests[0].location is ToolLocation.DESKTOP
