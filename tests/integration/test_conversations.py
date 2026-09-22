from uuid import uuid4

import pytest

from src.conversations.domain import ConversationCreate, ConversationStatus, TurnState
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.llm import domain as llm_domain
from src.core.llm.domain import TokenUsage, ToolCall
from src.core.tools.domain import ToolResult
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


@pytest.fixture
async def owner(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
    return await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email="enc::founder@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )


@pytest.fixture
async def conversation(db_session, owner):
    return await conversations_adapter.create(
        db_session,
        ConversationCreate(
            organization_id=owner.organization_id,
            user_id=owner.id,
            title="First thread",
        ),
    )


async def test_a_new_conversation_starts_idle(conversation):
    assert conversation.turn.status is ConversationStatus.IDLE
    assert conversation.turn.iterations_used == 0
    assert conversation.turn.pending_tool_calls == ()


async def test_a_conversation_round_trips(db_session, conversation):
    found = await conversations_adapter.get_for_user(db_session, conversation.id, conversation.user_id)

    assert found is not None
    assert found.title == "First thread"
    assert found.user_id == conversation.user_id


async def test_conversations_are_listed_for_their_user(db_session, owner, conversation):
    found = await conversations_adapter.list_for_user(db_session, owner.id)

    assert [c.id for c in found] == [conversation.id]


async def test_another_users_conversations_are_not_listed(db_session, conversation):
    assert await conversations_adapter.list_for_user(db_session, uuid4()) == []


async def test_messages_come_back_in_order(db_session, conversation):
    await conversations_adapter.append_messages(
        db_session,
        conversation.id,
        [llm_domain.user("first"), llm_domain.assistant("second")],
    )

    messages = await conversations_adapter.list_messages_for_user(db_session, conversation.id, conversation.user_id)

    assert [m["content"] for m in messages] == ["first", "second"]


async def test_appending_continues_the_position_sequence(db_session, conversation):
    await conversations_adapter.append_messages(db_session, conversation.id, [llm_domain.user("a")])
    await conversations_adapter.append_messages(db_session, conversation.id, [llm_domain.user("b")])

    messages = await conversations_adapter.list_messages_for_user(db_session, conversation.id, conversation.user_id)

    assert [m["content"] for m in messages] == ["a", "b"]


async def test_appending_nothing_is_a_no_op(db_session, conversation):
    assert await conversations_adapter.append_messages(db_session, conversation.id, []) == 0


async def test_block_content_survives_postgres(db_session, conversation):
    blocks = [
        {"type": "thinking", "thinking": "reasoning", "signature": "sig"},
        {"type": "text", "text": "the answer"},
    ]
    await conversations_adapter.append_messages(
        db_session, conversation.id, [llm_domain.assistant(blocks)]
    )

    messages = await conversations_adapter.list_messages_for_user(db_session, conversation.id, conversation.user_id)

    assert messages[0]["content"] == blocks


async def test_tool_calls_and_results_survive_postgres(db_session, conversation):
    call = ToolCall(id="c1", name="ReadFile", args={"path": "x.txt"})
    await conversations_adapter.append_messages(
        db_session,
        conversation.id,
        [llm_domain.assistant("", (call,)), llm_domain.tool_result("c1", "contents")],
    )

    messages = await conversations_adapter.list_messages_for_user(db_session, conversation.id, conversation.user_id)

    assert messages[0]["tool_calls"][0]["id"] == "c1"
    assert messages[0]["tool_calls"][0]["args"] == {"path": "x.txt"}
    assert messages[1]["tool_call_id"] == "c1"


async def test_turn_state_is_saved_and_restored(db_session, conversation):
    turn = TurnState(
        status=ConversationStatus.AWAITING_APPROVAL,
        pending_tool_calls=(ToolCall(id="c1", name="DeleteFile", args={"path": "x"}),),
        completed_tool_results=(ToolResult(tool_call_id="c0", content="done"),),
        iterations_used=7,
        usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
    )

    await conversations_adapter.save_turn_state(db_session, conversation.id, turn)
    found = await conversations_adapter.get_for_user(db_session, conversation.id, conversation.user_id)

    assert found is not None
    assert found.turn.status is ConversationStatus.AWAITING_APPROVAL
    assert found.turn.pending_tool_calls[0].name == "DeleteFile"
    assert found.turn.pending_tool_calls[0].args == {"path": "x"}
    assert found.turn.completed_tool_results[0].content == "done"
    assert found.turn.iterations_used == 7
    assert found.turn.usage.total_tokens == 120


async def test_saving_state_for_a_missing_conversation_returns_none(db_session):
    assert await conversations_adapter.save_turn_state(db_session, uuid4(), TurnState()) is None


async def test_deleting_a_conversation_cascades_to_its_messages(db_session, conversation):
    from sqlalchemy import func, select

    from src.conversations.sqlalchemy.models import MessageRow

    await conversations_adapter.append_messages(db_session, conversation.id, [llm_domain.user("a")])

    deleted = await conversations_adapter.delete_for_user(
        db_session, conversation.id, conversation.user_id
    )
    remaining = await db_session.execute(
        select(func.count()).select_from(MessageRow).where(
            MessageRow.conversation_id == conversation.id
        )
    )

    assert deleted is True
    assert remaining.scalar_one() == 0


async def test_deleting_a_missing_conversation_returns_false(db_session):
    assert await conversations_adapter.delete_for_user(db_session, uuid4(), uuid4()) is False


async def test_deleting_a_user_removes_their_conversations(db_session, owner, conversation):
    await users_adapter.delete_user(db_session, owner.id)

    assert await conversations_adapter.get_for_user(db_session, conversation.id, conversation.user_id) is None


async def test_a_conversation_reloads_as_valid_loop_state(db_session, conversation):
    call = ToolCall(id="c1", name="ReadFile", args={"path": "x.txt"})
    await conversations_adapter.append_messages(
        db_session,
        conversation.id,
        [
            llm_domain.user("read it"),
            llm_domain.assistant("", (call,)),
            llm_domain.tool_result("c1", "contents"),
        ],
    )

    messages = await conversations_adapter.list_messages_for_user(db_session, conversation.id, conversation.user_id)

    from langchain_core.messages import convert_to_messages

    assert [type(m).__name__ for m in convert_to_messages(messages)] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]


async def test_another_user_cannot_read_the_conversation(db_session, conversation):
    assert await conversations_adapter.get_for_user(db_session, conversation.id, uuid4()) is None


async def test_another_user_cannot_read_the_messages(db_session, conversation):
    await conversations_adapter.append_messages(db_session, conversation.id, [llm_domain.user("a")])

    assert (
        await conversations_adapter.list_messages_for_user(db_session, conversation.id, uuid4())
        is None
    )


async def test_an_owned_but_empty_thread_returns_an_empty_list(db_session, conversation):
    messages = await conversations_adapter.list_messages_for_user(
        db_session, conversation.id, conversation.user_id
    )

    assert messages == []


async def test_another_user_cannot_delete_the_conversation(db_session, conversation):
    deleted = await conversations_adapter.delete_for_user(db_session, conversation.id, uuid4())

    assert deleted is False
    assert (
        await conversations_adapter.get_for_user(db_session, conversation.id, conversation.user_id)
        is not None
    )
