"""A person's folders for their chats, over HTTP on the real app: what the desktop app calls.

Folders are personal, one level deep, and filing a chat never deletes or reorders anything."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.conversations.domain import ConversationCreate
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.database.sqlalchemy.core import async_session_factory
from src.fastapi.main import app
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
API = "/api/desktop/v1"
FOLDERS = f"{API}/conversation-folders"


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    yield


def sign_up(client, organization_id=None, role=Role.OWNER):
    """Someone with two chats of their own (in a new organization unless one is given)."""
    email = f"folders-{uuid4().hex[:10]}@example.com"
    hashing, encryption = app.state.hashing_service, app.state.encryption_service
    found: dict = {}

    async def seed():
        async with async_session_factory() as session:
            organization = (
                None if organization_id else await organizations_adapter.create(session, OrganizationCreate(name="Folders Co"))
            )
            org_id = organization_id or organization.id
            user = await users_adapter.create(
                session,
                UserCreate(
                    organization_id=org_id,
                    encrypted_email=encryption.encrypt(email),
                    email_hash=hashing.deterministic_hash(email),
                    password_hash=hashing.hash_password(PASSWORD),
                    role=role,
                ),
            )
            chats = [
                await conversations_adapter.create(
                    session, ConversationCreate(organization_id=org_id, user_id=user.id, title=f"Chat {n}")
                )
                for n in (1, 2)
            ]
            await session.commit()
            found.update(organization=org_id, user=user.id, chats=[c.id for c in chats])

    client.portal.call(seed)
    token = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD, "deviceName": "Folders"}).json()["token"]
    found["headers"] = {"Authorization": f"Bearer {token}"}
    return found


@pytest.fixture
def person(client):
    return sign_up(client)


def make(client, person, name):
    response = client.post(FOLDERS, json={"name": name}, headers=person["headers"])
    assert response.status_code == 201, response.text
    return response.json()


def chats(client, person):
    return {c["id"]: c for c in client.get(f"{API}/conversations", headers=person["headers"]).json()}


def file_chat(client, person, chat, folder_id):
    return client.patch(f"{API}/conversations/{chat}/folder", json={"folderId": folder_id}, headers=person["headers"])


# --- making, listing, renaming -------------------------------------------------------------------------


def test_a_folder_is_made_and_listed_by_name(client, person):
    made = make(client, person, "  Acme   Corp ")

    assert made["name"] == "Acme Corp"  # trimmed, inner spaces tidied
    listed = client.get(FOLDERS, headers=person["headers"]).json()
    assert [f["name"] for f in listed] == ["Acme Corp"]


def test_the_folders_come_back_in_alphabetical_order_whatever_the_capitals(client, person):
    for name in ["beta", "Alpha", "gamma"]:
        make(client, person, name)

    assert [f["name"] for f in client.get(FOLDERS, headers=person["headers"]).json()] == ["Alpha", "beta", "gamma"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_a_folder_needs_a_name_that_is_not_blank_or_too_long(client, person, name):
    response = client.post(FOLDERS, json={"name": name}, headers=person["headers"])

    assert response.status_code == 422
    assert response.json()["code"] in {"folder_name_required", "folder_name_too_long"}
    assert client.get(FOLDERS, headers=person["headers"]).json() == []


def test_one_letter_names_are_fine(client, person):
    assert make(client, person, "A")["name"] == "A"


def test_two_folders_cannot_share_a_name_whatever_its_capitals(client, person):
    make(client, person, "Acme")

    again = client.post(FOLDERS, json={"name": "ACME"}, headers=person["headers"])

    assert again.status_code == 409
    assert again.json()["code"] == "folder_name_taken"


def test_the_limit_is_fifty_folders_each(client, person):
    for n in range(50):
        make(client, person, f"Folder {n}")

    over = client.post(FOLDERS, json={"name": "One more"}, headers=person["headers"])

    assert over.status_code == 409
    assert over.json()["code"] == "conversation_folder_limit_reached"


def test_a_folder_is_renamed_and_may_keep_its_own_name_in_other_capitals(client, person):
    folder = make(client, person, "Acme")

    renamed = client.patch(f"{FOLDERS}/{folder['id']}", json={"name": "ACME"}, headers=person["headers"])

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "ACME"


def test_renaming_onto_another_folders_name_is_refused(client, person):
    make(client, person, "Acme")
    other = make(client, person, "Beta")

    refused = client.patch(f"{FOLDERS}/{other['id']}", json={"name": "acme"}, headers=person["headers"])

    assert refused.status_code == 409
    assert refused.json()["code"] == "folder_name_taken"


# --- filing chats -----------------------------------------------------------------------------------


def test_a_chat_is_filed_in_a_folder_and_taken_out_again(client, person):
    folder = make(client, person, "Acme")
    chat = str(person["chats"][0])

    filed = file_chat(client, person, chat, folder["id"])

    assert filed.status_code == 200, filed.text
    assert filed.json()["folderId"] == folder["id"]
    assert chats(client, person)[chat]["folderId"] == folder["id"]
    assert chats(client, person)[str(person["chats"][1])]["folderId"] is None

    out = file_chat(client, person, chat, None)
    assert out.status_code == 200
    assert chats(client, person)[chat]["folderId"] is None


def test_filing_a_chat_does_not_change_when_it_was_last_active(client, person):
    folder = make(client, person, "Acme")
    chat = str(person["chats"][0])
    before = chats(client, person)[chat]["updatedAt"]

    file_chat(client, person, chat, folder["id"])

    assert chats(client, person)[chat]["updatedAt"] == before


def test_deleting_a_folder_puts_its_chats_back_in_the_main_list_and_deletes_none(client, person):
    folder = make(client, person, "Acme")
    for chat in person["chats"]:
        file_chat(client, person, str(chat), folder["id"])

    deleted = client.delete(f"{FOLDERS}/{folder['id']}", headers=person["headers"])

    assert deleted.status_code == 204
    assert client.get(FOLDERS, headers=person["headers"]).json() == []
    after = chats(client, person)
    assert set(after) == {str(c) for c in person["chats"]}
    assert all(c["folderId"] is None for c in after.values())


def test_deleting_a_chat_leaves_its_folder(client, person):
    folder = make(client, person, "Acme")
    chat = str(person["chats"][0])
    file_chat(client, person, chat, folder["id"])

    assert client.delete(f"{API}/conversations/{chat}", headers=person["headers"]).status_code == 200

    assert [f["id"] for f in client.get(FOLDERS, headers=person["headers"]).json()] == [folder["id"]]


# --- whose they are --------------------------------------------------------------------------------


def test_nobody_else_sees_a_folder_even_in_the_same_organization(client, person):
    make(client, person, "Mine")
    colleague = sign_up(client, organization_id=person["organization"], role=Role.MEMBER)

    assert client.get(FOLDERS, headers=colleague["headers"]).json() == []
    # and both may have a folder of the same name
    assert make(client, colleague, "Mine")["name"] == "Mine"


def test_someone_elses_folder_cannot_be_renamed_deleted_or_filed_into(client, person):
    folder = make(client, person, "Mine")
    thief = sign_up(client, organization_id=person["organization"], role=Role.ADMIN)

    renamed = client.patch(f"{FOLDERS}/{folder['id']}", json={"name": "Taken"}, headers=thief["headers"])
    deleted = client.delete(f"{FOLDERS}/{folder['id']}", headers=thief["headers"])
    filed = file_chat(client, thief, str(thief["chats"][0]), folder["id"])

    assert (renamed.status_code, deleted.status_code, filed.status_code) == (404, 404, 404)
    assert filed.json()["code"] == "conversation_folder_not_found"
    assert [f["name"] for f in client.get(FOLDERS, headers=person["headers"]).json()] == ["Mine"]
    assert chats(client, thief)[str(thief["chats"][0])]["folderId"] is None


def test_someone_elses_chat_cannot_be_filed(client, person):
    folder = make(client, person, "Mine")
    other = sign_up(client, organization_id=person["organization"], role=Role.MEMBER)

    filed = client.patch(
        f"{API}/conversations/{other['chats'][0]}/folder", json={"folderId": folder["id"]}, headers=person["headers"]
    )

    assert filed.status_code == 404
    assert filed.json()["code"] == "conversation_not_found"


def test_an_unknown_folder_is_not_found(client, person):
    ghost = str(uuid4())

    assert client.patch(f"{FOLDERS}/{ghost}", json={"name": "x1"}, headers=person["headers"]).status_code == 404
    assert client.delete(f"{FOLDERS}/{ghost}", headers=person["headers"]).status_code == 404
    assert file_chat(client, person, str(person["chats"][0]), ghost).status_code == 404


def test_every_folder_route_needs_a_signed_in_person(client):
    assert client.get(FOLDERS).status_code == 401
    assert client.post(FOLDERS, json={"name": "Acme"}).status_code == 401
    assert client.patch(f"{API}/conversations/{uuid4()}/folder", json={"folderId": None}).status_code == 401
