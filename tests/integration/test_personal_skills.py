"""A person's own skills, on a real database: the organization's skills stay everyone's, an
operator's are theirs alone, and neither can be touched from the other's side."""

from uuid import uuid4

import pytest
from helpers import FakeBucketStore, FakeLLM, make_completion

from src.assistants.sql import sql_tool_context
from src.core.exceptions import ConflictError
from src.core.llm.domain import ToolCall
from src.knowledge import context as knowledge_context
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.skills import config as skills_config
from src.skills import tools as skills_tools
from src.skills import use_cases as skills_use_cases
from src.skills.domain import SkillCreate
from src.skills.sqlalchemy import adapter as skills_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

BODY = "# Steps\n\n1. Do the thing.\n2. Check it."


async def person(db_session, organization_id, role):
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
async def team(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme"))
    owner = await person(db_session, organization.id, Role.OWNER)
    ana = await person(db_session, organization.id, Role.MEMBER)
    beto = await person(db_session, organization.id, Role.MEMBER)
    await db_session.commit()
    return organization, owner, ana, beto


def skill(organization, name, owner=None, instructions=BODY, description="Does a thing."):
    return SkillCreate(
        organization_id=organization.id,
        name=name,
        description=description,
        instructions=instructions,
        owner_id=owner.id if owner else None,
    )


async def names(db_session, organization, user=None):
    listed = await skills_adapter.list_for_organization(db_session, organization.id, user.id if user else None)
    return {s.name: s.owner_id for s in listed}


# --- who sees what ---------------------------------------------------------------------------


async def test_a_personal_skill_is_seen_only_by_its_owner(db_session, team):
    organization, owner, ana, beto = team
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report"))
    await skills_adapter.upsert(db_session, skill(organization, "ana-notes", owner=ana))
    await db_session.commit()

    assert set(await names(db_session, organization, ana)) == {"weekly-report", "ana-notes"}
    assert set(await names(db_session, organization, beto)) == {"weekly-report"}
    assert set(await names(db_session, organization, owner)) == {"weekly-report"}
    # the management page lists only the organization's own
    assert set(await names(db_session, organization)) == {"weekly-report"}


async def test_a_personal_skill_cannot_be_read_by_name_by_someone_else(db_session, team):
    organization, _, ana, beto = team
    await skills_adapter.upsert(db_session, skill(organization, "ana-notes", owner=ana))
    await db_session.commit()

    assert (await skills_adapter.get_for_organization(db_session, "ana-notes", organization.id, ana.id)).owner_id == ana.id
    assert await skills_adapter.get_for_organization(db_session, "ana-notes", organization.id, beto.id) is None
    assert await skills_adapter.get_for_organization(db_session, "ana-notes", organization.id) is None


async def test_a_person_may_share_a_name_with_an_organization_skill_and_theirs_is_the_one_they_get(
    db_session, team
):
    organization, _, ana, beto = team
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report", instructions="the org way"))
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report", owner=ana, instructions="ana's way"))
    await db_session.commit()

    mine = await skills_adapter.get_for_organization(db_session, "weekly-report", organization.id, ana.id)
    theirs = await skills_adapter.get_for_organization(db_session, "weekly-report", organization.id, beto.id)

    assert (mine.instructions, mine.owner_id) == ("ana's way", ana.id)
    assert (theirs.instructions, theirs.owner_id) == ("the org way", None)
    # listed once for her, not twice
    listed = await skills_adapter.list_for_organization(db_session, organization.id, ana.id)
    assert [s.name for s in listed] == ["weekly-report"]
    assert listed[0].owner_id == ana.id


async def test_saving_a_personal_skill_never_overwrites_the_organizations(db_session, team):
    organization, _, ana, _ = team
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report", instructions="the org way"))
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report", owner=ana, instructions="ana's way"))
    await db_session.commit()

    shared = await skills_adapter.get_in_scope(db_session, "weekly-report", organization.id, None)

    assert shared.instructions == "the org way"


async def test_two_people_can_each_have_a_skill_of_the_same_name(db_session, team):
    organization, _, ana, beto = team
    await skills_adapter.upsert(db_session, skill(organization, "my-notes", owner=ana, instructions="a"))
    await skills_adapter.upsert(db_session, skill(organization, "my-notes", owner=beto, instructions="b"))
    await db_session.commit()

    a = await skills_adapter.get_for_organization(db_session, "my-notes", organization.id, ana.id)
    b = await skills_adapter.get_for_organization(db_session, "my-notes", organization.id, beto.id)

    assert (a.instructions, b.instructions) == ("a", "b")


async def test_saving_again_replaces_the_row_instead_of_adding_one(db_session, team):
    organization, _, ana, _ = team
    await skills_adapter.upsert(db_session, skill(organization, "my-notes", owner=ana, instructions="one"))
    await skills_adapter.upsert(db_session, skill(organization, "my-notes", owner=ana, instructions="two"))
    await db_session.commit()

    assert await skills_adapter.count_personal(db_session, ana.id) == 1
    assert (await skills_adapter.get_in_scope(db_session, "my-notes", organization.id, ana.id)).instructions == "two"


async def test_a_persons_skills_do_not_count_against_the_organizations_limit_and_go_with_them(db_session, team):
    organization, _, ana, _ = team
    await skills_adapter.upsert(db_session, skill(organization, "shared"))
    await skills_adapter.upsert(db_session, skill(organization, "mine", owner=ana))
    await db_session.commit()

    assert await skills_adapter.count_for_organization(db_session, organization.id) == 1
    await users_adapter.delete_user(db_session, ana.id)
    await db_session.commit()
    assert set(await names(db_session, organization)) == {"shared"}
    assert await skills_adapter.count_personal(db_session, ana.id) == 0


async def test_deleting_removes_only_that_scope(db_session, team):
    organization, _, ana, _ = team
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report"))
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report", owner=ana))
    await db_session.commit()

    assert await skills_adapter.delete_for_organization(db_session, "weekly-report", organization.id, ana.id) is True

    left = await skills_adapter.get_for_organization(db_session, "weekly-report", organization.id, ana.id)
    assert left.owner_id is None  # the organization's is still there


# --- what the agent shows ----------------------------------------------------------------------


async def test_the_listing_marks_a_persons_own_skill_and_hides_it_from_others(db_session, team):
    organization, _, ana, beto = team
    await skills_adapter.upsert(db_session, skill(organization, "weekly-report"))
    await skills_adapter.upsert(db_session, skill(organization, "ana-notes", owner=ana))
    await db_session.commit()

    for_ana = knowledge_context.render(await skills_adapter.list_for_organization(db_session, organization.id, ana.id), [])
    for_beto = knowledge_context.render(await skills_adapter.list_for_organization(db_session, organization.id, beto.id), [])

    assert "- ana-notes (yours):" in for_ana
    assert "- weekly-report:" in for_ana
    assert "ana-notes" not in for_beto


# --- the limits -------------------------------------------------------------------------------------


async def save(db_session, organization, user, name, owner_id):
    return await skills_use_cases.save_skill(
        organization_id=organization.id,
        instructions=BODY,
        created_by=user.id,
        count_skills_fn=lambda org: skills_adapter.count_for_organization(db_session, org),
        get_skill_fn=lambda name, org: skills_adapter.get_for_organization(db_session, name, org, user.id),
        upsert_skill_fn=lambda created: skills_adapter.upsert(db_session, created),
        name=name,
        description="Does a thing.",
        owner_id=owner_id,
        count_personal_skills_fn=lambda uid: skills_adapter.count_personal(db_session, uid),
        get_skill_in_scope_fn=lambda name, org, owner: skills_adapter.get_in_scope(db_session, name, org, owner),
    )


async def test_one_person_may_keep_fifteen_skills_of_their_own_and_no_more(db_session, team):
    organization, _, ana, _ = team
    for n in range(skills_config.MAX_PERSONAL_SKILLS_PER_USER):
        await save(db_session, organization, ana, f"skill-{n}", ana.id)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc:
        await save(db_session, organization, ana, "one-too-many", ana.id)

    assert exc.value.code == "skill_personal_limit_reached"
    assert skills_config.MAX_PERSONAL_SKILLS_PER_USER == 15
    # updating one she has is not a new skill
    await save(db_session, organization, ana, "skill-0", ana.id)


async def test_the_limit_is_per_person_and_apart_from_the_organizations(db_session, team):
    organization, _, ana, beto = team
    for n in range(skills_config.MAX_PERSONAL_SKILLS_PER_USER):
        await save(db_session, organization, ana, f"skill-{n}", ana.id)
    await db_session.commit()

    await save(db_session, organization, beto, "his-first", beto.id)
    await save(db_session, organization, ana, "an-org-skill", None)  # the organization's own limit


# --- through the agent's tools ---------------------------------------------------------------------


def tools_for(db_session, user, llm=None):
    async def factory(preferred=(), temperature=0.0):
        if llm is None:
            raise AssertionError("this test builds no model")
        return llm

    context = sql_tool_context(
        db_session,
        organization_id=user.organization_id,
        user_id=user.id,
        user_role=str(user.role),
        bucket_store=FakeBucketStore(),
        credentials={},
        llm_factory=factory,
    )
    return skills_tools.build(context)


def builder(name, text="# Steps\n\n1. Do it."):
    """A model that writes the skill: reads it, saves it, summarises."""
    return FakeLLM(
        make_completion("", (ToolCall(id="r", name="ReadSkill", args={"name": name}),)),
        make_completion(
            "",
            (ToolCall(id="s", name="SaveSkill", args={"name": name, "description": "Does it.", "instructions": text}),),
        ),
        "Saved.",
    )


async def test_an_operators_skill_is_always_their_own_even_if_they_ask_for_a_shared_one(db_session, team):
    organization, _, ana, beto = team
    tools = tools_for(db_session, ana, builder("my-flow"))

    await tools["BuildSkill"].handler(skill_name="my-flow", description="a flow", personal=False)
    await db_session.commit()

    saved = await skills_adapter.get_in_scope(db_session, "my-flow", organization.id, ana.id)
    assert saved is not None and saved.owner_id == ana.id
    assert await skills_adapter.get_in_scope(db_session, "my-flow", organization.id, None) is None
    assert "my-flow" not in await names(db_session, organization, beto)


async def test_an_owner_writes_for_the_organization_by_default_and_for_themselves_on_request(db_session, team):
    organization, owner, ana, _ = team

    await tools_for(db_session, owner, builder("house-style"))["BuildSkill"].handler(
        skill_name="house-style", description="the house style"
    )
    await tools_for(db_session, owner, builder("owner-only"))["BuildSkill"].handler(
        skill_name="owner-only", description="just for me", personal=True
    )
    await db_session.commit()

    assert (await skills_adapter.get_in_scope(db_session, "house-style", organization.id, None)) is not None
    assert (await skills_adapter.get_in_scope(db_session, "owner-only", organization.id, owner.id)) is not None
    assert "house-style" in await names(db_session, organization, ana)  # everyone has it
    assert "owner-only" not in await names(db_session, organization, ana)


async def test_the_approval_says_whether_a_skill_is_for_one_person_or_everyone(db_session, team):
    _, owner, ana, _ = team

    owner_tool = tools_for(db_session, owner)["BuildSkill"]
    member_tool = tools_for(db_session, ana)["BuildSkill"]

    assert "everyone in the organization will see it" in owner_tool.describe(skill_name="x", description="d")
    assert "only you will see it" in owner_tool.describe(skill_name="x", description="d", personal=True)
    assert "only you will see it" in member_tool.describe(skill_name="x", description="d", personal=False)


async def test_a_person_deletes_only_their_own_skills_and_is_told_where_the_organizations_are_managed(
    db_session, team
):
    organization, _, ana, _ = team
    await skills_adapter.upsert(db_session, skill(organization, "shared"))
    await skills_adapter.upsert(db_session, skill(organization, "mine", owner=ana))
    await db_session.commit()
    tools = tools_for(db_session, ana)

    assert "Deleted your skill 'mine'" in await tools["DeleteMySkill"].handler(name="mine")
    refused = await tools["DeleteMySkill"].handler(name="shared")

    assert "no skill of your own" in refused and "owners and admins" in refused
    assert "shared" in await names(db_session, organization, ana)


# --- a skill the person brings, kept as it is -----------------------------------------------------

BROUGHT = """---
name: weekly-recap
description: Write the weekly recap for the client.
triggers:
  - write this week's recap
---

# Weekly recap

Run `node recap.js`, then send it.
"""


async def test_a_skill_brought_from_elsewhere_is_kept_exactly_and_is_the_persons_own(db_session, team):
    organization, _, ana, beto = team
    tools = tools_for(db_session, ana)

    reply = await tools["ImportSkill"].handler(instructions=BROUGHT)
    await db_session.commit()

    saved = await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id)
    assert saved.owner_id == ana.id
    assert saved.description == "Write the weekly recap for the client."
    assert saved.triggers == ["write this week's recap"]
    # nothing was rewritten, adapted or "fixed": the body is what she brought
    assert "Run `node recap.js`, then send it." in saved.instructions
    assert "exactly as written" in reply and "yours alone" in reply
    assert "weekly-recap" not in await names(db_session, organization, beto)


async def test_an_import_needs_a_name_from_the_file_or_the_caller(db_session, team):
    _, _, ana, _ = team
    tools = tools_for(db_session, ana)
    nameless = "---\ndescription: No name.\n---\n\nDo it."

    from src.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        await tools["ImportSkill"].handler(instructions=nameless)
    assert exc.value.code == "skill_name_missing"

    assert "Saved skill 'given-name'" in await tools["ImportSkill"].handler(instructions=nameless, name="given-name")


async def test_an_operator_cannot_import_for_the_whole_organization(db_session, team):
    organization, _, ana, _ = team

    await tools_for(db_session, ana)["ImportSkill"].handler(instructions=BROUGHT, personal=False)
    await db_session.commit()

    assert await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, None) is None
    assert (await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id)) is not None


async def test_an_owner_can_import_for_the_whole_organization_and_it_asks_first(db_session, team):
    organization, owner, ana, _ = team
    tool = tools_for(db_session, owner)["ImportSkill"]

    await tool.handler(instructions=BROUGHT)
    await db_session.commit()

    assert tool.requires_approval is True
    assert "for the whole organization" in tool.describe(instructions=BROUGHT, name="weekly-recap")
    assert "weekly-recap" in await names(db_session, organization, ana)


async def test_importing_counts_against_the_personal_limit(db_session, team):
    organization, _, ana, _ = team
    tools = tools_for(db_session, ana)
    for n in range(skills_config.MAX_PERSONAL_SKILLS_PER_USER):
        await tools["ImportSkill"].handler(instructions=BROUGHT, name=f"recap-{n}")
    await db_session.commit()

    with pytest.raises(ConflictError) as exc:
        await tools["ImportSkill"].handler(instructions=BROUGHT, name="one-too-many")

    assert exc.value.code == "skill_personal_limit_reached"


# --- the files a skill points to travel with it ----------------------------------------------------

TEMPLATE = "<h1>{{client}}</h1>\n<p>{{summary}}</p>"
LAWS = "# Laws\n\nEvery figure has a source."


async def test_a_skill_brought_with_its_templates_keeps_them_and_the_agent_can_read_them(db_session, team):
    organization, _, ana, beto = team
    tools = tools_for(db_session, ana)

    reply = await tools["ImportSkill"].handler(
        instructions=BROUGHT, files={"templates/report.html": TEMPLATE, "laws.md": LAWS}
    )
    await db_session.commit()

    saved = await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id)
    assert saved.files == {"templates/report.html": TEMPLATE, "laws.md": LAWS}
    assert "laws.md, templates/report.html" in reply

    # she reads a template the way the agent does: ReadSkill with the file's path
    from src.assistants.sql import sql_tool_ports
    from src.knowledge import tools as knowledge_tools

    ports = sql_tool_ports(db_session, user_id=ana.id)
    read = knowledge_tools.build(
        get_document_fn=ports.get_document_fn,
        get_document_text_fn=ports.get_document_text_fn,
        get_skill_fn=ports.get_skill_fn,
        organization_id=organization.id,
    )["ReadSkill"].handler
    assert await read(name="weekly-recap", file="templates/report.html") == TEMPLATE
    assert "templates/report.html" in await read(name="weekly-recap")  # the skill lists what it carries

    # and nobody else has the skill or its templates
    other = sql_tool_ports(db_session, user_id=beto.id)
    assert await other.get_skill_fn("weekly-recap", organization.id) is None


async def test_importing_the_text_again_keeps_the_files_it_already_has(db_session, team):
    organization, _, ana, _ = team
    tools = tools_for(db_session, ana)
    await tools["ImportSkill"].handler(instructions=BROUGHT, files={"laws.md": LAWS})

    await tools["ImportSkill"].handler(instructions=BROUGHT.replace("send it", "send it today"))
    await db_session.commit()

    saved = await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id)
    assert saved.files == {"laws.md": LAWS}
    assert "send it today" in saved.instructions


async def test_sending_the_files_again_replaces_them(db_session, team):
    organization, _, ana, _ = team
    tools = tools_for(db_session, ana)
    await tools["ImportSkill"].handler(instructions=BROUGHT, files={"laws.md": LAWS, "old.md": "x"})

    await tools["ImportSkill"].handler(instructions=BROUGHT, files={"laws.md": "# New laws"})
    await db_session.commit()

    saved = await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id)
    assert saved.files == {"laws.md": "# New laws"}


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"../escape.md": "x"}, "skill_file_path_invalid"),
        ({"/abs.md": "x"}, "skill_file_path_invalid"),
        ({"SKILL.md": "x"}, "skill_file_path_invalid"),
        ({"big.md": "x" * (skills_config.MAX_FILE_CHARS + 1)}, "skill_file_too_long"),
        ({f"f{n}.md": "x" for n in range(skills_config.MAX_FILES_PER_SKILL + 1)}, "skill_files_too_many"),
    ],
    ids=["climbs-out", "absolute", "the-skill-itself", "too-long", "too-many"],
)
async def test_bad_reference_files_are_refused_and_nothing_is_saved(db_session, team, files, code):
    from src.core.exceptions import ValidationError

    organization, _, ana, _ = team

    with pytest.raises(ValidationError) as exc:
        await tools_for(db_session, ana)["ImportSkill"].handler(instructions=BROUGHT, files=files)

    assert exc.value.code == code
    assert await skills_adapter.get_in_scope(db_session, "weekly-recap", organization.id, ana.id) is None


async def test_the_tool_tells_the_agent_to_pass_every_file_and_that_binaries_do_not_fit(db_session, team):
    _, _, ana, _ = team
    schema = tools_for(db_session, ana)["ImportSkill"].schema

    assert "files" in schema.model_fields
    assert "read each one" in schema.__doc__ and "or it is lost" in schema.__doc__
    assert "logo, image or font cannot be kept" in schema.__doc__
