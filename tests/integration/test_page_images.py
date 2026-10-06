import base64
from uuid import uuid4

import pytest
from helpers import FakeBucketStore
from starlette.testclient import TestClient

from src.api import dependencies as api_dependencies
from src.api.main import app
from src.core.settings import settings
from src.exports import tools as export_tools
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects import html_images, links
from src.projects.files import ProjectFiles
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


async def make_user(db_session, name="Acme"):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name=name))
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
def public_api(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "http://localhost:8000")


@pytest.fixture
async def drafts(db_session):
    user = await make_user(db_session)
    bucket = FakeBucketStore()
    files = ProjectFiles(db_session, user.organization_id, user.id, bucket)
    project = await files.create_project("Borradores")
    image = await files.write(project, "cat-mouse-merida/cat.png", PNG, content_type="image/png")
    await db_session.commit()
    return files, project, image, bucket


async def page_source(files, project, path):
    _, raw = await files.read_bytes(project, path)
    return raw.decode()


async def test_a_saved_page_links_the_project_image_it_points_at(db_session, drafts, public_api):
    files, project, image, _ = drafts

    await files.write(project, "report/report.html", b'<img src="../cat-mouse-merida/cat.png" alt="Merida">')

    html = await page_source(files, project, "report/report.html")
    assert html == f'<img src="{links.view_url(image.id)}" alt="Merida">'


async def test_a_path_to_nothing_is_left_as_written(db_session, drafts, public_api):
    files, project, _, _ = drafts
    page = b'<img src="../nowhere/cat.png"><img src="https://example.com/x.png">'

    await files.write(project, "report/report.html", page)

    assert await page_source(files, project, "report/report.html") == page.decode()


async def test_without_a_public_address_the_path_is_kept(db_session, drafts, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", None)
    files, project, _, _ = drafts

    await files.write(project, "report/report.html", b'<img src="../cat-mouse-merida/cat.png">')

    assert "../cat-mouse-merida/cat.png" in await page_source(files, project, "report/report.html")


@pytest.mark.parametrize("written", ["path", "link"])
async def test_export_puts_the_image_inside_the_page(db_session, drafts, public_api, monkeypatch, written):
    files, project, image, _ = drafts
    source = "../cat-mouse-merida/cat.png" if written == "path" else links.view_url(image.id)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", None)  # keep the page exactly as written
    await files.write(project, "report/report.html", f'<img src="{source}">'.encode())

    html, missing = await files.embed_images(
        project, "report/report.html", await page_source(files, project, "report/report.html")
    )

    assert missing == []
    assert html == f'<img src="data:image/png;base64,{base64.b64encode(PNG).decode()}">'


async def test_export_names_the_images_it_could_not_include(db_session, drafts):
    files, project, _, _ = drafts

    _, missing = await files.embed_images(project, "report/report.html", '<img src="../cat-mouse-merida/dog.png">')

    assert missing == ["../cat-mouse-merida/dog.png"]


async def test_export_will_not_pull_in_another_organizations_image(db_session, drafts, public_api):
    files, project, _, _ = drafts
    other = await make_user(db_session, "Other")
    theirs_files = ProjectFiles(db_session, other.organization_id, other.id, FakeBucketStore())
    theirs = await theirs_files.write(
        await theirs_files.create_project("Private"), "secret.png", PNG, content_type="image/png"
    )
    await db_session.commit()

    _, missing = await files.embed_images(project, "report/report.html", f'<img src="{links.view_url(theirs.id)}">')

    assert len(missing) == 1


async def test_the_conversion_result_warns_about_missing_images(db_session, drafts, monkeypatch):
    files, project, _, bucket = drafts
    await files.write(project, "report/report.html", b'<img src="../nowhere.png">')
    await db_session.commit()

    from src.exports import render

    monkeypatch.setattr(render, "to_pdf", lambda html, **_: render.Rendered(b"%PDF", 1.0, 1))

    class Context:
        session = db_session
        organization_id = files._organization_id
        user_id = files._user_id
        bucket_store = bucket

    tool = export_tools.build(Context())["HtmlToPdf"]  # type: ignore[arg-type]
    result = await tool.handler(project="Borradores", path="report/report.html")

    assert "WARNING: 1 image(s)" in result
    assert "../nowhere.png" in result


# --- the link itself ------------------------------------------------------------------


@pytest.fixture
def client_with(drafts):
    _, _, _, bucket = drafts
    bucket.download_url = "http://localhost:9090/the-way/key?X-Amz-Signature=abc"
    app.dependency_overrides[api_dependencies.get_bucket_store] = lambda: bucket
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


async def test_the_link_redirects_to_a_fresh_bucket_url(drafts, client_with):
    _, _, image, bucket = drafts

    response = client_with.get(
        f"/api/v1/files/{image.id}/view", params={"sig": links.sign(image.id)}, follow_redirects=False
    )

    assert response.status_code == 307
    assert response.headers["location"] == bucket.download_url
    assert bucket.presigned_gets[-1][1] == 15 * 60


async def test_a_wrong_signature_finds_nothing(drafts, client_with):
    _, _, image, _ = drafts

    response = client_with.get(f"/api/v1/files/{image.id}/view", params={"sig": "0" * 32}, follow_redirects=False)

    assert response.status_code == 404


async def test_only_images_are_served_by_link(db_session, drafts, client_with):
    files, project, _, _ = drafts
    page = await files.write(project, "report/report.html", b"<p>private</p>")
    await db_session.commit()

    response = client_with.get(f"/api/v1/files/{page.id}/view", params={"sig": links.sign(page.id)}, follow_redirects=False)

    assert response.status_code == 404


def test_the_address_finder_sees_a_link_written_by_any_api_address():
    file_id = uuid4()
    html = f'<img src="https://api.example.com/api/v1/files/{file_id}/view?sig={links.sign(file_id)}">'

    assert links.parse(html_images.references(html)[0]) == file_id
