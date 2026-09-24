from uuid import uuid4

import pytest
from helpers import FakeEncryptionService, make_completion

from src.api_keys.domain import ApiKeyCreate, Provider
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.documents import config, summaries
from src.documents import tasks as document_tasks
from src.documents.domain import DocumentCreate, DocumentStatus
from src.documents.sqlalchemy import adapter as documents_adapter
from src.knowledge import tools as knowledge_tools
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

BRAND_TEXT = (
    "Signal Orange is the single accent. It is never used for body text, never "
    "tinted, and never placed on a photographic background."
)

GENERATED = "Accent colour rules for Signal Orange, including where it may not be used."


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


async def give_key(db_session, organization, user, provider=Provider.OPENAI):
    await api_keys_adapter.upsert(
        db_session,
        ApiKeyCreate(
            organization_id=organization.id,
            user_id=user.id,
            provider=provider,
            encrypted_secret="enc::sk-secret-1234",
            last_four="1234",
            issued_by=user.id,
        ),
    )
    await db_session.commit()


async def extracted_document(db_session, organization, user, text=BRAND_TEXT, **overrides):
    payload = {
        "organization_id": organization.id,
        "title": "Brand Book",
        "description": "",
        "filename": "brand.docx",
        "content_type": "application/msword",
        "size_bytes": 2048,
        "uploaded_by": user.id,
    }
    payload.update(overrides)
    document = await documents_adapter.create(db_session, DocumentCreate(**payload))
    await documents_adapter.save_extraction(
        db_session, document.id, DocumentStatus.EXTRACTED, text
    )
    await db_session.commit()
    return document


class RecordingLLM:
    def __init__(self, reply: str = GENERATED) -> None:
        self.reply = reply
        self.calls = 0

    async def respond(self, messages, tools=()):
        self.calls += 1
        return make_completion(self.reply)


@pytest.fixture
def model(monkeypatch):
    built = {}
    llm = RecordingLLM()

    def fake_build_model(name, temperature=0.0, *, api_key):
        built["model"] = name
        built["api_key"] = api_key
        return object()

    monkeypatch.setattr(summaries.llm_providers, "build_model", fake_build_model)
    monkeypatch.setattr(summaries, "LangchainLLM", lambda _m: llm)
    llm.built = built
    return llm


async def train(db_session, organization, user):
    from src.documents import training

    trained, described = await training.train_organization(
        db_session, organization.id, user.id, FakeEncryptionService()
    )
    await db_session.commit()
    return trained, described


async def test_an_uploaded_document_is_not_trained_yet(db_session, tenant, model):
    organization, user = tenant
    await extracted_document(db_session, organization, user)

    held = await documents_adapter.list_for_organization(db_session, organization.id)

    assert held[0].status is DocumentStatus.EXTRACTED


async def test_an_untrained_document_is_invisible_to_the_agent(db_session, tenant, model):
    organization, user = tenant
    await extracted_document(db_session, organization, user)

    assert await knowledge_tools.build_context(db_session, organization.id) == ""


async def test_training_makes_it_visible(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)

    await train(db_session, organization, user)

    block = await knowledge_tools.build_context(db_session, organization.id)
    assert "Brand Book" in block


async def test_training_writes_the_generated_description(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await extracted_document(db_session, organization, user)

    await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert stored.description == GENERATED
    assert stored.status is DocumentStatus.TRAINED


async def test_the_generated_line_is_what_the_agent_sees(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)

    await train(db_session, organization, user)

    block = await knowledge_tools.build_context(db_session, organization.id)
    assert GENERATED in block


async def test_the_trainers_key_and_the_mini_model_are_used(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)

    await train(db_session, organization, user)

    assert model.built["model"] == config.SUMMARY_MODEL[Provider.OPENAI]
    assert model.built["api_key"] == "sk-secret-1234"


async def test_a_hand_written_description_is_never_replaced(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await extracted_document(
        db_session, organization, user, description="Written by the admin."
    )

    await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert stored.description == "Written by the admin."
    assert stored.status is DocumentStatus.TRAINED
    assert model.calls == 0


async def test_training_reports_what_it_did(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)
    await extracted_document(
        db_session, organization, user, title="Policies", description="Already written."
    )

    trained, described = await train(db_session, organization, user)

    assert (trained, described) == (2, 1)


async def test_training_is_idempotent(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)

    await train(db_session, organization, user)
    trained, _described = await train(db_session, organization, user)

    assert trained == 0
    assert model.calls == 1


async def test_a_trainer_with_no_key_still_trains_without_a_description(
    db_session, tenant, model
):
    organization, user = tenant
    document = await extracted_document(db_session, organization, user)

    trained, described = await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert (trained, described) == (1, 0)
    assert stored.status is DocumentStatus.TRAINED
    assert stored.description == ""


async def test_a_failing_model_still_trains_the_document(
    db_session, tenant, model, monkeypatch
):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await extracted_document(db_session, organization, user)

    async def explode(**_kwargs):
        raise RuntimeError("provider is down")

    from src.documents import training

    monkeypatch.setattr(training.summaries, "describe", explode)

    trained, described = await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert (trained, described) == (1, 0)
    assert stored.status is DocumentStatus.TRAINED


async def test_an_unsupported_document_is_never_trained(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await documents_adapter.create(
        db_session,
        DocumentCreate(
            organization_id=organization.id,
            title="Logo",
            description="",
            filename="logo.png",
            content_type="image/png",
            size_bytes=64,
            uploaded_by=user.id,
        ),
    )
    await documents_adapter.save_extraction(
        db_session, document.id, DocumentStatus.UNSUPPORTED, None
    )
    await db_session.commit()

    trained, _described = await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert trained == 0
    assert stored.status is DocumentStatus.UNSUPPORTED


async def test_training_is_scoped_to_one_organization(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    other, other_user = await make_org(db_session, name="Rival Ltd")
    await db_session.commit()
    await extracted_document(db_session, organization, user)
    theirs = await extracted_document(db_session, other, other_user)

    await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, theirs.id)
    assert stored.status is DocumentStatus.EXTRACTED


async def test_an_edited_description_survives_a_later_training_run(
    db_session, tenant, model
):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await extracted_document(db_session, organization, user)
    await train(db_session, organization, user)

    await documents_adapter.update_for_organization(
        db_session, document.id, organization.id, {"description": "Corrected by hand."}
    )
    await db_session.commit()
    await train(db_session, organization, user)

    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert stored.description == "Corrected by hand."


async def test_the_untrained_count_drives_the_button(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    await extracted_document(db_session, organization, user)
    await extracted_document(db_session, organization, user, title="Policies")

    assert await documents_adapter.count_untrained(db_session, organization.id) == 2

    await train(db_session, organization, user)

    assert await documents_adapter.count_untrained(db_session, organization.id) == 0


async def test_the_worker_task_trains_the_whole_organization(db_session, tenant, model):
    organization, user = tenant
    await give_key(db_session, organization, user)
    document = await extracted_document(db_session, organization, user)

    await document_tasks.run_training(
        organization.id, user.id, FakeEncryptionService()
    )

    await db_session.rollback()
    stored = await documents_adapter.get_by_id(db_session, document.id)
    assert stored.status is DocumentStatus.TRAINED
    assert stored.description == GENERATED
