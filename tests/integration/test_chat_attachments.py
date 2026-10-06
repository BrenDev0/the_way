from uuid import uuid4

import pytest
from helpers import FakeBucketStore, FakeLLM

from src.conversations import routes as conversation_routes
from src.conversations import tasks as conversation_tasks
from src.conversations import use_cases as conversations_use_cases
from src.conversations.domain import ConversationCreate
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.exceptions import ValidationError
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects import keys
from src.projects.domain import FileStatus
from src.projects.files import ProjectFiles
from src.projects.sqlalchemy import adapter as projects_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

def _png() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(out, "PNG")
    return out.getvalue()


PNG = _png()


async def make_user(db_session, organization_id=None):
    if organization_id is None:
        organization_id = (await organizations_adapter.create(db_session, OrganizationCreate(name="Acme"))).id
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization_id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.MEMBER,
        ),
    )
    await db_session.commit()
    return user


async def attach(files: ProjectFiles, name="gato.png", content=PNG, content_type="image/png"):
    """What the desktop app does: a ticket, the bytes to the bucket, complete."""
    project = await files.project("Borradores")
    project_file, _ = await files.upload_ticket(project, "adjuntos", name, content_type, len(content))
    key = keys.file_key(project.organization_id, project_file.id)
    files._bucket.objects[key] = len(content)
    files._bucket.contents[key] = content
    await projects_adapter.update_file(
        files._session, project_file.id, {"status": FileStatus.READY, "size_bytes": len(content)}
    )
    await files._session.commit()
    return project_file


@pytest.fixture
async def member(db_session):
    user = await make_user(db_session)
    return user, ProjectFiles(db_session, user.organization_id, user.id, FakeBucketStore())


async def test_an_attachment_lands_in_drafts_and_never_replaces_one(db_session, member):
    _, files = member

    first = await attach(files)
    second = await attach(files)

    assert first.name == "gato.png"
    assert second.name == "gato (2).png"


async def test_a_message_refers_to_the_users_own_finished_file(db_session, member):
    _, files = member
    attached = await attach(files)

    (block,) = await conversation_routes._attachment_blocks(files, [attached.id])

    assert block["project"] == "Borradores"
    assert block["path"] == "adjuntos/gato.png"
    assert block["content_type"] == "image/png"


async def test_someone_elses_file_cannot_be_attached(db_session, member):
    owner, _ = member
    colleague = await make_user(db_session, owner.organization_id)
    theirs = await attach(ProjectFiles(db_session, colleague.organization_id, colleague.id, FakeBucketStore()))
    _, files = member

    with pytest.raises(ValidationError):
        await conversation_routes._attachment_blocks(files, [theirs.id])


async def test_the_model_sees_the_attached_picture(db_session, member):
    user, files = member
    attached = await attach(files)
    conversation = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=user.organization_id, user_id=user.id, title="Nueva conversación")
    )
    await db_session.commit()
    await conversations_use_cases.send_message(
        conversation_id=conversation.id,
        user_id=user.id,
        message="¿qué es esto?",
        get_conversation_for_user_fn=lambda cid, uid: conversations_adapter.get_for_user(db_session, cid, uid),
        append_messages_fn=lambda cid, msgs: conversations_adapter.append_messages(db_session, cid, msgs),
        save_turn_state_fn=lambda cid, turn: conversations_adapter.save_turn_state(db_session, cid, turn),
        attachments=await conversation_routes._attachment_blocks(files, [attached.id]),
    )
    await db_session.commit()
    llm = FakeLLM("Es un gato.")

    await conversation_tasks.run_turn(conversation.id, llm=llm, bucket_store=files._bucket)

    sent = next(message for message in llm.received[0] if message["role"] == "user")
    assert [block["type"] for block in sent["content"]] == ["text", "text", "image"]
    # the stored message still holds only the reference
    await db_session.rollback()
    stored = (await conversations_adapter.list_messages(db_session, conversation.id))[0]
    assert stored["content"][1]["type"] == "attachment"
