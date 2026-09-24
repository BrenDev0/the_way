from uuid import uuid4

import pytest

from src.documents.domain import DocumentCreate, DocumentStatus
from src.documents.sqlalchemy import adapter as documents_adapter
from src.knowledge import tools as knowledge_tools
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.skills.domain import SkillCreate
from src.skills.sqlalchemy import adapter as skills_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

BRAND_TEXT = "Our palette is ink, bone and a single warm accent. Never use gradients."


async def make_org(db_session, name="Acme Inc"):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name=name)
    )
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
    return organization, user


@pytest.fixture
async def tenant(db_session):
    organization, user = await make_org(db_session)
    await db_session.commit()
    return organization, user


def document_for(organization_id, user_id, **overrides):
    payload = {
        "organization_id": organization_id,
        "title": "Brand Book",
        "description": "Palette and tone.",
        "filename": "brand.pdf",
        "content_type": "application/pdf",
        "size_bytes": 2048,
        "uploaded_by": user_id,
    }
    payload.update(overrides)
    return DocumentCreate(**payload)


async def trained_document(db_session, organization_id, user_id, text=BRAND_TEXT, **overrides):
    document = await documents_adapter.create(
        db_session, document_for(organization_id, user_id, **overrides)
    )
    await documents_adapter.save_extraction(
        db_session, document.id, DocumentStatus.EXTRACTED, text
    )
    await documents_adapter.save_status(db_session, document.id, DocumentStatus.TRAINED)
    await db_session.commit()
    return document


async def test_extracted_text_round_trips(db_session, tenant):
    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)

    text = await documents_adapter.get_text(db_session, document.id, organization.id)

    assert text == BRAND_TEXT


async def test_listing_does_not_carry_the_extracted_text(db_session, tenant):
    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)

    listed = await documents_adapter.list_for_organization(db_session, organization.id)

    assert len(listed) == 1
    assert not hasattr(listed[0], "extracted_text")
    assert listed[0].extracted_chars == len(BRAND_TEXT)


async def test_another_organization_cannot_read_the_text(db_session, tenant):
    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)

    assert await documents_adapter.get_text(db_session, document.id, uuid4()) is None


async def test_another_organization_cannot_list_the_document(db_session, tenant):
    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)

    assert await documents_adapter.list_for_organization(db_session, uuid4()) == []


async def test_deleting_the_organization_takes_its_documents(db_session, tenant):
    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)

    await organizations_adapter.delete_by_id(db_session, organization.id)
    await db_session.commit()

    assert await documents_adapter.list_for_organization(db_session, organization.id) == []


async def test_a_skill_upsert_replaces_rather_than_duplicating(db_session, tenant):
    organization, user = tenant

    first = await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="brand-voice",
            description="First",
            instructions="one",
            created_by=user.id,
        ),
    )
    second = await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="brand-voice",
            description="Second",
            instructions="two",
            created_by=user.id,
        ),
    )
    await db_session.commit()

    held = await skills_adapter.list_for_organization(db_session, organization.id)

    assert len(held) == 1
    assert second.id == first.id
    assert held[0].instructions == "two"


async def test_two_organizations_may_share_a_skill_name(db_session, tenant):
    organization, user = tenant
    other, other_user = await make_org(db_session, name="Rival Ltd")
    await db_session.commit()

    for org, owner in ((organization, user), (other, other_user)):
        await skills_adapter.upsert(
            db_session,
            SkillCreate(
                organization_id=org.id,
                name="brand-voice",
                description="d",
                instructions="i",
                created_by=owner.id,
            ),
        )
    await db_session.commit()

    assert len(await skills_adapter.list_for_organization(db_session, organization.id)) == 1
    assert len(await skills_adapter.list_for_organization(db_session, other.id)) == 1


async def test_the_read_tool_returns_the_document_text(db_session, tenant):
    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)

    tools = knowledge_tools.build(db_session, organization.id)
    result = await tools["ReadKnowledgeDocument"].handler(document_id=str(document.id))

    assert result == BRAND_TEXT


async def test_the_read_tool_refuses_another_organizations_document(db_session, tenant):
    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)

    tools = knowledge_tools.build(db_session, uuid4())
    result = await tools["ReadKnowledgeDocument"].handler(document_id=str(document.id))

    assert "No document with id" in result


async def test_the_read_tool_rejects_a_malformed_id(db_session, tenant):
    organization, _user = tenant

    tools = knowledge_tools.build(db_session, organization.id)
    result = await tools["ReadKnowledgeDocument"].handler(document_id="not-a-uuid")

    assert "No document with id" in result


async def test_the_read_tool_truncates_a_long_document(db_session, tenant):
    from src.knowledge import config as knowledge_config

    organization, user = tenant
    document = await trained_document(
        db_session, organization.id, user.id, text="x" * 60_000
    )

    tools = knowledge_tools.build(db_session, organization.id)
    result = await tools["ReadKnowledgeDocument"].handler(document_id=str(document.id))

    assert len(result) < knowledge_config.MAX_TOOL_READ_CHARS + 500
    assert "truncated" in result


async def test_the_skill_tool_returns_instructions(db_session, tenant):
    organization, user = tenant
    await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="brand-voice",
            description="d",
            instructions="1. Be warm.",
            created_by=user.id,
        ),
    )
    await db_session.commit()

    tools = knowledge_tools.build(db_session, organization.id)

    assert await tools["ReadSkill"].handler(name="brand-voice") == "1. Be warm."


async def test_the_skill_tool_refuses_another_organizations_skill(db_session, tenant):
    organization, user = tenant
    await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="brand-voice",
            description="d",
            instructions="1. Be warm.",
            created_by=user.id,
        ),
    )
    await db_session.commit()

    tools = knowledge_tools.build(db_session, uuid4())
    result = await tools["ReadSkill"].handler(name="brand-voice")

    assert "No skill named" in result


async def test_the_turn_context_lists_what_the_organization_holds(db_session, tenant):
    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)
    await skills_adapter.upsert(
        db_session,
        SkillCreate(
            organization_id=organization.id,
            name="brand-voice",
            description="How to write.",
            instructions="1. Be warm.",
            created_by=user.id,
        ),
    )
    await db_session.commit()

    block = await knowledge_tools.build_context(db_session, organization.id)

    assert "brand-voice: How to write." in block
    assert "Brand Book: Palette and tone." in block


async def test_the_turn_context_is_empty_for_a_fresh_organization(db_session, tenant):
    organization, _user = tenant

    assert await knowledge_tools.build_context(db_session, organization.id) == ""


async def test_an_unextracted_document_is_kept_out_of_the_context(db_session, tenant):
    organization, user = tenant
    await documents_adapter.create(
        db_session, document_for(organization.id, user.id, title="Still Ingesting")
    )
    await db_session.commit()

    assert await knowledge_tools.build_context(db_session, organization.id) == ""


class ToolCallingLLM:
    def __init__(self, call_name: str, args: dict) -> None:
        from src.core.llm.domain import ToolCall

        self.turns = 0
        self.tools_seen: list[tuple] = []
        self.tool_results: list[str] = []
        self._call = ToolCall(id="call-1", name=call_name, args=args)

    async def respond(self, messages, tools=()):
        from helpers import make_completion

        self.tools_seen.append(tuple(t.__name__ for t in tools))
        self.tool_results.extend(
            str(m.get("content")) for m in messages if m.get("role") == "tool"
        )
        self.turns += 1
        if self.turns == 1:
            return make_completion("", tool_calls=(self._call,))
        return make_completion("The accent colour is Signal Orange.")


async def start_running_conversation(db_session, organization, user):
    from src.conversations import use_cases as conversations_use_cases
    from src.conversations.domain import ConversationCreate
    from src.conversations.sqlalchemy import adapter as conversations_adapter

    conversation = await conversations_adapter.create(
        db_session,
        ConversationCreate(
            organization_id=organization.id, user_id=user.id, title="Knowledge turn"
        ),
    )
    await conversations_use_cases.send_message(
        conversation_id=conversation.id,
        user_id=user.id,
        message="what is our accent colour",
        get_conversation_for_user_fn=lambda cid, uid: conversations_adapter.get_for_user(
            db_session, cid, uid
        ),
        append_messages_fn=lambda cid, msgs: conversations_adapter.append_messages(
            db_session, cid, msgs
        ),
        save_turn_state_fn=lambda cid, turn: conversations_adapter.save_turn_state(
            db_session, cid, turn
        ),
    )
    await db_session.commit()
    return conversation


async def test_a_turn_tells_the_model_about_the_knowledge_tools(db_session, tenant):
    from src.conversations import tasks as conversation_tasks

    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)
    conversation = await start_running_conversation(db_session, organization, user)

    llm = ToolCallingLLM("ReadSkill", {"name": "nope"})
    await conversation_tasks.run_turn(conversation.id, llm=llm)

    assert set(llm.tools_seen[0]) == {"ReadKnowledgeDocument", "ReadSkill"}


async def test_a_turn_carries_the_knowledge_index_in_its_context(db_session, tenant):
    from src.conversations import tasks as conversation_tasks
    from src.core.llm.domain import Message

    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)
    conversation = await start_running_conversation(db_session, organization, user)

    seen: list[list[Message]] = []

    class Recorder(ToolCallingLLM):
        async def respond(self, messages, tools=()):
            seen.append(list(messages))
            return await super().respond(messages, tools)

    await conversation_tasks.run_turn(
        conversation.id, llm=Recorder("ReadSkill", {"name": "nope"})
    )

    systems = [m["content"] for m in seen[0] if m["role"] == "system"]
    assert any("Brand Book" in str(block) for block in systems)


async def test_the_model_can_read_a_document_mid_turn(db_session, tenant):
    from src.conversations import tasks as conversation_tasks

    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)
    conversation = await start_running_conversation(db_session, organization, user)

    llm = ToolCallingLLM("ReadKnowledgeDocument", {"document_id": str(document.id)})
    await conversation_tasks.run_turn(conversation.id, llm=llm)

    assert llm.turns == 2
    assert BRAND_TEXT in llm.tool_results[0]


async def test_the_tool_result_is_persisted_with_the_turn(db_session, tenant):
    from src.conversations import tasks as conversation_tasks
    from src.conversations.sqlalchemy import adapter as conversations_adapter

    organization, user = tenant
    document = await trained_document(db_session, organization.id, user.id)
    conversation = await start_running_conversation(db_session, organization, user)

    llm = ToolCallingLLM("ReadKnowledgeDocument", {"document_id": str(document.id)})
    await conversation_tasks.run_turn(conversation.id, llm=llm)

    await db_session.rollback()
    messages = await conversations_adapter.list_messages(db_session, conversation.id)

    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert BRAND_TEXT in messages[2]["content"]
    assert messages[3]["content"] == "The accent colour is Signal Orange."


async def test_the_system_prompt_stays_the_cacheable_prefix(db_session, tenant):
    from src.conversations import prompt
    from src.conversations import tasks as conversation_tasks

    organization, user = tenant
    await trained_document(db_session, organization.id, user.id)
    conversation = await start_running_conversation(db_session, organization, user)

    seen = []

    class Recorder(ToolCallingLLM):
        async def respond(self, messages, tools=()):
            seen.append(list(messages))
            return await super().respond(messages, tools)

    await conversation_tasks.run_turn(
        conversation.id, llm=Recorder("ReadSkill", {"name": "nope"})
    )

    assert seen[0][0]["content"] == prompt.SYSTEM
