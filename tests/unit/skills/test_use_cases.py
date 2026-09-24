from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.skills import config, frontmatter
from src.skills import use_cases as skills_use_cases

SKILL_MD = """---
name: brand-voice
description: How to write in the company voice. Use for any customer-facing copy.
---
1. Be warm.
2. Be plain.
"""


@pytest.fixture
def organization_id():
    return uuid4()


@pytest.fixture
def save(organization_id):
    saved = []

    async def run(count: int = 0, existing=None, **overrides):
        async def count_skills_fn(_organization_id):
            return count

        async def get_skill_fn(_name, _organization_id):
            return existing

        async def upsert_skill_fn(skill):
            saved.append(skill)
            return skill

        payload = {
            "organization_id": organization_id,
            "instructions": SKILL_MD,
            "created_by": uuid4(),
            "count_skills_fn": count_skills_fn,
            "get_skill_fn": get_skill_fn,
            "upsert_skill_fn": upsert_skill_fn,
        }
        payload.update(overrides)
        return await skills_use_cases.save_skill(**payload)

    run.saved = saved
    return run


async def test_the_name_comes_out_of_the_frontmatter(save):
    await save()

    assert save.saved[0].name == "brand-voice"


async def test_the_description_comes_out_of_the_frontmatter(save):
    await save()

    assert save.saved[0].description.startswith("How to write in the company voice")


async def test_the_frontmatter_is_stripped_from_the_instructions(save):
    await save()

    assert save.saved[0].instructions == "1. Be warm.\n2. Be plain."


async def test_an_explicit_name_beats_the_frontmatter(save):
    await save(name="tone-of-voice")

    assert save.saved[0].name == "tone-of-voice"


async def test_plain_markdown_with_a_supplied_name_works(save):
    await save(instructions="Just do the thing.", name="do-thing")

    assert save.saved[0].instructions == "Just do the thing."


async def test_a_skill_with_no_name_anywhere_is_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(instructions="Just do the thing.")

    assert exc.value.code == "skill_name_missing"


@pytest.mark.parametrize("name", ["Brand Voice", "brand_voice", "-brand", "brand-", "a--b"])
async def test_a_name_that_is_not_kebab_case_is_refused(save, name):
    with pytest.raises(ValidationError) as exc:
        await save(name=name)

    assert exc.value.code == "skill_name_invalid"


@pytest.mark.parametrize("name", ["brand", "brand-voice", "brand-voice-2", "a1-b2"])
async def test_kebab_case_names_are_accepted(save, name):
    await save(name=name)

    assert save.saved[-1].name == name


async def test_a_skill_with_no_instructions_is_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(instructions="---\nname: empty\n---\n", name="empty")

    assert exc.value.code == "skill_instructions_missing"


async def test_an_overlong_description_is_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(description="x" * (config.MAX_DESCRIPTION_CHARS + 1))

    assert exc.value.code == "skill_description_too_long"


async def test_a_full_organization_is_refused(save):
    with pytest.raises(ConflictError) as exc:
        await save(count=config.MAX_SKILLS_PER_ORGANIZATION)

    assert exc.value.code == "skill_limit_reached"


async def test_updating_an_existing_skill_ignores_the_limit(save):
    from helpers import make_skill

    await save(count=config.MAX_SKILLS_PER_ORGANIZATION, existing=make_skill())

    assert save.saved[0].name == "brand-voice"


async def test_deleting_a_missing_skill_is_not_found():
    async def delete_skill_fn(_name, _organization_id):
        return False

    with pytest.raises(NotFoundError) as exc:
        await skills_use_cases.delete_skill(
            name="nope",
            organization_id=uuid4(),
            delete_skill_fn=delete_skill_fn,
        )

    assert exc.value.code == "skill_not_found"
    assert exc.value.status_code == 404


def test_frontmatter_without_a_fence_is_all_body():
    name, description, body = frontmatter.parse("just instructions")

    assert (name, description) == (None, None)
    assert body == "just instructions"


def test_frontmatter_keeps_colons_in_the_description():
    _name, description, _body = frontmatter.parse(
        "---\nname: x\ndescription: Use when: the user asks\n---\nbody"
    )

    assert description == "Use when: the user asks"


def test_indented_frontmatter_keys_still_parse():
    name, _description, _body = frontmatter.parse("---\n  name: spaced\n---\nbody")

    assert name == "spaced"


def test_an_unterminated_fence_yields_no_body():
    name, _description, body = frontmatter.parse("---\nname: x\nstill going")

    assert name == "x"
    assert body == ""


async def test_a_name_is_normalised_to_lower_case(save):
    await save(name="Brand-Voice")

    assert save.saved[-1].name == "brand-voice"


async def test_surrounding_whitespace_is_trimmed_from_a_name(save):
    await save(name="  brand-voice  ")

    assert save.saved[-1].name == "brand-voice"
