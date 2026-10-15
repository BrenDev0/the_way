"""The organization's library: one per organization, every member reads it, only owners
and admins change it (and only through the routes), and no agent ever writes to it."""

import io
from uuid import uuid4

import pytest
from helpers import FakeBucketStore
from PIL import Image

from src.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from src.knowledge.tools import build_context
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects import config as projects_config
from src.projects import use_cases
from src.projects.files import ProjectFiles
from src.projects.management import use_cases as management_use_cases
from src.projects.sqlalchemy import adapter as projects_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

LIBRARY = projects_config.LIBRARY_PROJECT


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, format="PNG")
    return out.getvalue()


async def make_user(db_session, organization_id, role):
    return await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization_id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=role,
        ),
    )


@pytest.fixture
async def org(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Agencia"))
    admin = await make_user(db_session, organization.id, Role.ADMIN)
    member = await make_user(db_session, organization.id, Role.MEMBER)
    library = await projects_adapter.get_or_create_library(db_session, organization.id, LIBRARY)
    await db_session.commit()
    return organization, admin, member, library


def getter(db_session):
    return lambda project_id, organization_id: projects_adapter.get_project(db_session, project_id, organization_id)


async def test_there_is_one_library_per_organization(db_session, org):
    organization, _, _, library = org

    again = await projects_adapter.get_or_create_library(db_session, organization.id, LIBRARY)

    assert again.id == library.id
    assert library.shared and library.owner_id is None


async def test_every_member_reads_it_and_only_managers_change_it(db_session, org):
    _, admin, member, library = org
    get = getter(db_session)

    assert (await use_cases.resolve_readable_project(library.id, member, get)).id == library.id
    assert (await use_cases.resolve_writable_project(library.id, admin, get)).id == library.id
    with pytest.raises(AuthorizationError):
        await use_cases.resolve_writable_project(library.id, member, get)
    # it is no one's, so no one can rename or delete it as their own
    with pytest.raises(NotFoundError):
        await use_cases.resolve_owned_project(library.id, admin, get)


async def test_another_organization_cannot_see_it(db_session, org):
    _, _, _, library = org
    other = await organizations_adapter.create(db_session, OrganizationCreate(name="Otra"))
    stranger = await make_user(db_session, other.id, Role.OWNER)

    with pytest.raises(NotFoundError):
        await use_cases.resolve_readable_project(library.id, stranger, getter(db_session))


async def test_an_orphaned_project_is_not_shared(db_session, org):
    organization, admin, member, _ = org
    mine = await ProjectFiles(db_session, organization.id, admin.id, FakeBucketStore()).create_project("Privado")
    # what deleting the admin's account leaves: an orphan, for managers to reassign
    await projects_adapter.update_project(db_session, mine.id, {"owner_id": None})

    with pytest.raises(NotFoundError):
        await use_cases.resolve_readable_project(mine.id, member, getter(db_session))


async def test_management_neither_lists_nor_touches_it(db_session, org):
    organization, _, _, library = org

    listed = await projects_adapter.list_projects_for_organization(db_session, organization.id)

    assert library.id not in [p.id for p in listed]
    with pytest.raises(NotFoundError):
        await management_use_cases.resolve_organization_project(library.id, organization.id, getter(db_session))


async def test_its_name_is_reserved(db_session, org):
    organization, _, member, _ = org
    files = ProjectFiles(db_session, organization.id, member.id, FakeBucketStore())

    with pytest.raises(ConflictError):
        await files.create_project("biblioteca")


async def test_an_agent_reads_it_but_never_writes_there(db_session, org):
    organization, admin, member, library = org
    bucket = FakeBucketStore()
    await _admin_upload(db_session, library, admin, bucket)
    files = ProjectFiles(db_session, organization.id, member.id, bucket)

    found, inner = await files.source(await files.workspace(), f"project:{LIBRARY}/Soullens/logo.png")
    assert (found.id, inner) == (library.id, "Soullens/logo.png")
    _, content = await files.read_bytes(found, inner)
    assert content == png()

    for attempt in (
        lambda: files.write(library, "Soullens/logo.png", b"draft", overwrite=True),
        lambda: files.make_folder(library, "Nueva"),
        lambda: files.delete(library, "Soullens/logo.png"),
        lambda: files.move(library, "Soullens/logo.png", "otro.png"),
    ):
        with pytest.raises(AuthorizationError):
            await attempt()
    # even working for an admin
    with pytest.raises(AuthorizationError):
        await ProjectFiles(db_session, organization.id, admin.id, bucket).write(library, "x.png", png())


async def test_the_agent_is_told_what_each_brand_has(db_session, org):
    organization, admin, _, library = org
    await _admin_upload(db_session, library, admin, FakeBucketStore())

    listing = await build_context(db_session, organization.id)

    assert f"project:{LIBRARY}/Soullens/logo.png" in listing
    assert "- Soullens/: logo.png" in listing


async def _admin_upload(db_session, library, admin, bucket):
    """An upload through the panel: the routes' use cases, not the agent's files."""
    from src.projects import paths

    folder_id = await paths.ensure_folder(
        library, ["Soullens"],
        lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        lambda folder: projects_adapter.create_folder(db_session, folder),
    )
    await paths.store_file(
        project=library, folder_id=folder_id, name="logo.png", content=png(), content_type="image/png",
        uploaded_by=admin.id, overwrite=False,
        find_entry_fn=lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        create_file_fn=lambda f: projects_adapter.create_file(db_session, f),
        update_file_fn=lambda file_id, changes: projects_adapter.update_file(db_session, file_id, changes),
        bucket_store=bucket,
    )
    await db_session.commit()


async def _library_file(db_session, library, admin, bucket, path: str, content: bytes, content_type: str):
    from src.projects import paths

    *folders, name = path.split("/")
    folder_id = await paths.ensure_folder(
        library, folders,
        lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        lambda folder: projects_adapter.create_folder(db_session, folder),
    )
    await paths.store_file(
        project=library, folder_id=folder_id, name=name, content=content, content_type=content_type,
        uploaded_by=admin.id, overwrite=False,
        find_entry_fn=lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        create_file_fn=lambda f: projects_adapter.create_file(db_session, f),
        update_file_fn=lambda file_id, changes: projects_adapter.update_file(db_session, file_id, changes),
        bucket_store=bucket,
    )
    await db_session.commit()


def _page_builder(db_session, organization, member, bucket, llm):
    from src.core.tools.context import ToolContext
    from src.html_pages import tools as html_tools

    async def llm_factory(_models, _temperature=None):
        return llm

    context = ToolContext(
        session=db_session, organization_id=organization.id, user_id=member.id,
        user_role=Role.MEMBER, bucket_store=bucket, credentials={}, llm_factory=llm_factory,
    )
    return html_tools.build(context)["BuildHtmlPage"].handler


async def test_a_page_for_a_brand_carries_its_pack(db_session, org):
    from helpers import FakeLLM

    organization, admin, member, library = org
    bucket = FakeBucketStore()
    tokens = b":root { --paper: #FFFFFF; --fg: #0A0E1A; --brand: #0052FE; --ink: #0A0E1A; }"
    await _library_file(db_session, library, admin, bucket, "SLS/tokens.css", tokens, "text/css")
    await _library_file(db_session, library, admin, bucket, "SLS/voice.md", b"Never say synergy.", "text/markdown")
    await _library_file(db_session, library, admin, bucket, "SLS/logo/logo.png", png(), "image/png")
    llm = FakeLLM("Design brief.", "Built.")

    await _page_builder(db_session, organization, member, bucket, llm)(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", brand="sls",
    )

    designer_request = llm.received[0][-1]["content"]
    assert "=== BRAND PACK: SLS (binding) ===" in designer_request
    assert "--accent: #0052FE;" in designer_request
    assert f"project:{LIBRARY}/SLS/logo/logo.png" in designer_request
    assert "Never say synergy." in designer_request


async def test_a_logo_uploaded_in_the_panel_reaches_the_builder(db_session, org):
    from helpers import FakeLLM

    # The panel uploads into the brand folder itself: no logo/ subfolder.
    organization, admin, member, library = org
    bucket = FakeBucketStore()
    tokens = b":root { --paper: #FFFFFF; --fg: #0A0E1A; --brand: #0052FE; }"
    await _library_file(db_session, library, admin, bucket, "SLS/tokens.css", tokens, "text/css")
    await _library_file(db_session, library, admin, bucket, "SLS/logo-claro.png", png(), "image/png")
    await _library_file(db_session, library, admin, bucket, "SLS/hero.png", png(), "image/png")
    llm = FakeLLM("Design brief.", "Built.")

    await _page_builder(db_session, organization, member, bucket, llm)(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", brand="SLS",
    )

    designer_request = llm.received[0][-1]["content"]
    assert f"- project:{LIBRARY}/SLS/logo-claro.png" in designer_request
    assert f"project:{LIBRARY}/SLS/hero.png" not in designer_request
    assert "The pack has no logo file" not in designer_request


async def test_a_brand_without_a_pack_builds_nothing_and_names_the_ones_there(db_session, org):
    from helpers import FakeLLM

    organization, admin, member, library = org
    bucket = FakeBucketStore()
    await _library_file(db_session, library, admin, bucket, "SLS/tokens.css", b":root { --brand: #000; }", "text/css")
    llm = FakeLLM()

    result = await _page_builder(db_session, organization, member, bucket, llm)(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", brand="GRE",
    )

    assert result.startswith("No page was built")
    assert "Brand folders there: SLS." in result
    assert llm.received == []


KIT_PACKS = __import__("pathlib").Path(__file__).resolve().parents[3] / "the-way-kit" / "brand-packs"


@pytest.mark.skipif(not KIT_PACKS.is_dir(), reason="the kit is not cloned next to the backend")
async def test_the_kit_packs_load_into_the_library_and_reach_the_builder(db_session, org):
    from helpers import FakeLLM

    from src.projects import load_brands

    organization, admin, member, _ = org
    bucket = FakeBucketStore()
    packs = load_brands._packs(KIT_PACKS, [])

    loaded = await load_brands.load(db_session, bucket, organization.id, admin.id, packs)
    # again: replaced in place, not duplicated or refused
    await load_brands.load(db_session, bucket, organization.id, admin.id, packs)
    await db_session.commit()

    assert [item.brand for item in loaded] == ["ARKA", "EXA", "GRE", "SLS", "XST"]
    assert "SLS/logo/logo.webp" in loaded[3].files
    llm = FakeLLM("Design brief.", "Built.")
    await _page_builder(db_session, organization, member, bucket, llm)(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", brand="SLS",
    )
    designer_request = llm.received[0][-1]["content"]
    assert "--accent: #0052FE;" in designer_request
    assert f"project:{LIBRARY}/SLS/logo/logo-inverse.webp" in designer_request


async def test_only_owners_and_admins_load_brands(db_session, org):
    from src.core.cryptography.bcrypt.adapter import BcryptHashingService
    from src.projects import load_brands

    organization, _, _, _ = org
    email = f"member-{uuid4()}@example.com"
    await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id, encrypted_email="enc", password_hash="x", role=Role.MEMBER,
            email_hash=BcryptHashingService().deterministic_hash(email),
        ),
    )

    with pytest.raises(load_brands.LoadError, match="only owners and admins"):
        await load_brands.find_editor(db_session, email)
    with pytest.raises(load_brands.LoadError, match="No user"):
        await load_brands.find_editor(db_session, "nobody@example.com")


async def test_a_kit_document_gets_its_linked_layers_inside_it(db_session, org):
    organization, admin, member, library = org
    bucket = FakeBucketStore()
    await _library_file(db_session, library, admin, bucket, "SLS/tokens.css", b":root{--brand:#0052FE}", "text/css")
    files = ProjectFiles(db_session, organization.id, member.id, bucket)
    drafts = await files.project("Borradores")
    await files.write(drafts, "docs/core.css", b".doc{color:var(--brand)}")
    page = (
        '<html><head><link rel="stylesheet" href="core.css">'
        f'<link href="project:{LIBRARY}/SLS/tokens.css" rel="stylesheet">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Mada">'
        '<link rel="stylesheet" href="nowhere.css"><link rel="icon" href="x.png">'
        "</head><body></body></html>"
    )

    html, missing = await files.embed_stylesheets(drafts, "docs/plan.html", page)

    assert "<style>\n.doc{color:var(--brand)}\n</style>" in html
    assert "--brand:#0052FE" in html
    assert "fonts.googleapis.com" in html  # a URL elsewhere is the renderer's to allow
    assert 'rel="icon"' in html
    assert missing == ["nowhere.css"]


async def test_the_page_checker_holds_a_brand_page_to_its_voice_and_away_from_other_brands(db_session, org):
    from helpers import FakeLLM, make_completion

    from src.core.llm.domain import ToolCall

    organization, admin, member, library = org
    bucket = FakeBucketStore()
    sls_tokens = b":root { --paper: #FFFFFF; --fg: #0A0E1A; --brand: #0052FE; }"
    sls_voice = "## Words that never appear\n\nCotización / propuesta (say Plan Maestro instead); \"gratis\".".encode()
    await _library_file(db_session, library, admin, bucket, "SLS/tokens.css", sls_tokens, "text/css")
    await _library_file(db_session, library, admin, bucket, "SLS/voice.md", sls_voice, "text/markdown")
    gre_tokens = b":root { --brand: #C8A24B; }"
    gre_identity = "# GRE (Gin Real Estate) — Identity\n".encode()
    await _library_file(db_session, library, admin, bucket, "GRE/tokens.css", gre_tokens, "text/css")
    await _library_file(db_session, library, admin, bucket, "GRE/identity.md", gre_identity, "text/markdown")
    page = (
        '<!doctype html><html lang="es"><body><!-- precio por confirmar -->'
        "<h1>Pide tu cotización gratis</h1><p>Un proyecto de Gin Real Estate</p></body></html>"
    )
    llm = FakeLLM(
        "Design brief.",
        make_completion("", (ToolCall(id="w", name="WriteProjectFile", args={"project": "Borradores", "path": "p.html", "content": page}),)),
        make_completion("", (ToolCall(id="c", name="CheckPage", args={"project": "Borradores", "path": "p.html"}),)),
        "Built.",
    )

    await _page_builder(db_session, organization, member, bucket, llm)(
        project="Borradores", output_path="p.html", page_type="landing", brief="A page.", brand="SLS",
    )

    report = llm.received[-1][-1]["content"]
    report = report if isinstance(report, str) else report[0]["text"]
    assert "precio por confirmar" in report
    assert "'Cotización'" in report and "'gratis'" in report
    assert "the name 'Gin Real Estate' (GRE) appears in the copy" in report
