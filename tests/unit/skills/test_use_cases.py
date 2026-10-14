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
    name, description, body, _triggers = frontmatter.parse("just instructions")

    assert (name, description) == (None, None)
    assert body == "just instructions"


def test_frontmatter_keeps_colons_in_the_description():
    _name, description, _body, _triggers = frontmatter.parse(
        "---\nname: x\ndescription: Use when: the user asks\n---\nbody"
    )

    assert description == "Use when: the user asks"


def test_indented_frontmatter_keys_still_parse():
    name, _description, _body, _triggers = frontmatter.parse("---\n  name: spaced\n---\nbody")

    assert name == "spaced"


def test_an_unterminated_fence_yields_no_body():
    name, _description, body, _triggers = frontmatter.parse("---\nname: x\nstill going")

    assert name == "x"
    assert body == ""


FOLDED_SKILL_MD = """---
name: using-this-kit
description: >
  How to mount this kit on an agent and route work to the right skill.
  Read this first: the kit is a body of method an agent reads.
triggers:
  - "how do I use this kit"
  - "which skill should I use for this"
---

# Using this kit
"""


def test_a_folded_description_is_read_as_one_line():
    name, description, body, _triggers = frontmatter.parse(FOLDED_SKILL_MD)

    assert name == "using-this-kit"
    assert description == (
        "How to mount this kit on an agent and route work to the right skill. "
        "Read this first: the kit is a body of method an agent reads."
    )
    assert body == "# Using this kit"


def test_a_literal_description_keeps_its_line_breaks():
    _name, description, _body, _triggers = frontmatter.parse(
        "---\nname: x\ndescription: |\n  First line.\n  Second line.\n---\nbody"
    )

    assert description == "First line.\nSecond line."


def test_a_block_ends_at_the_next_key():
    name, description, _body, _triggers = frontmatter.parse(
        "---\ndescription: >-\n  Folded.\nname: after-the-block\n---\nbody"
    )

    assert description == "Folded."
    assert name == "after-the-block"


def test_key_like_text_inside_a_block_stays_in_the_block():
    name, description, _body, _triggers = frontmatter.parse(
        "---\nname: real\ndescription: >\n  Use when: asked.\n  name: not-a-key\n---\nbody"
    )

    assert name == "real"
    assert description == "Use when: asked. name: not-a-key"


def test_list_items_do_not_leak_into_fields():
    name, description, _body, _triggers = frontmatter.parse(
        "---\nname: x\ntriggers:\n  - \"description: no\"\ndescription: yes\n---\nbody"
    )

    assert (name, description) == ("x", "yes")


def test_quotes_around_a_value_are_removed():
    name, description, _body, _triggers = frontmatter.parse(
        "---\nname: \"quoted\"\ndescription: 'Use it: always'\n---\nbody"
    )

    assert (name, description) == ("quoted", "Use it: always")


async def test_a_folded_description_is_saved_not_its_marker(save):
    await save(instructions=FOLDED_SKILL_MD)

    assert save.saved[-1].description.startswith("How to mount this kit")


async def test_a_name_is_normalised_to_lower_case(save):
    await save(name="Brand-Voice")

    assert save.saved[-1].name == "brand-voice"


async def test_surrounding_whitespace_is_trimmed_from_a_name(save):
    await save(name="  brand-voice  ")

    assert save.saved[-1].name == "brand-voice"


KIT_SKILL_MD = """---
name: meeting-minutes
description: >
  Turn commitments into minutes with an owner and a date on every line.
triggers:
  - "write the minutes for the meeting with..."
  - "what did we agree on with..."
---

# Meeting minutes
"""


def test_triggers_come_out_of_the_frontmatter():
    parsed = frontmatter.parse(KIT_SKILL_MD)

    assert parsed.triggers == [
        "write the minutes for the meeting with...",
        "what did we agree on with...",
    ]


def test_list_items_may_sit_at_the_key_indentation():
    parsed = frontmatter.parse("---\nname: x\ntriggers:\n- one\n- two\n---\nbody")

    assert parsed.triggers == ["one", "two"]


def test_a_flow_list_of_triggers_is_read():
    parsed = frontmatter.parse("---\nname: x\ntriggers: [one, 'two, three']\n---\nbody")

    assert parsed.triggers[0] == "one"


async def test_a_skill_keeps_its_frontmatter_triggers(save):
    await save(instructions=KIT_SKILL_MD)

    assert save.saved[-1].triggers == [
        "write the minutes for the meeting with...",
        "what did we agree on with...",
    ]


async def test_explicit_triggers_beat_the_frontmatter(save):
    await save(instructions=KIT_SKILL_MD, triggers=["draft the recap"])

    assert save.saved[-1].triggers == ["draft the recap"]


async def test_triggers_are_tidied_and_deduplicated(save):
    await save(triggers=["  draft   the recap ", "Draft the recap", "", "send it"])

    assert save.saved[-1].triggers == ["draft the recap", "send it"]


async def test_too_many_triggers_are_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(triggers=[f"request {index}" for index in range(config.MAX_TRIGGERS + 1)])

    assert exc.value.code == "skill_triggers_too_many"


async def test_a_long_trigger_is_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(triggers=["x" * (config.MAX_TRIGGER_CHARS + 1)])

    assert exc.value.code == "skill_trigger_too_long"


async def test_saving_without_files_leaves_them_alone(save):
    await save()

    assert save.saved[-1].files is None


async def test_reference_files_are_saved_with_the_skill(save):
    await save(files={"laws.md": "# Laws", "engine/core.css": ":root {}"})

    assert save.saved[-1].files == {"laws.md": "# Laws", "engine/core.css": ":root {}"}


@pytest.mark.parametrize(
    "path", ["../secrets.md", "/abs.md", "a//b.md", "a/./b.md", "with space.md", "SKILL.md", ""]
)
async def test_a_reference_file_path_must_stay_inside_the_skill(save, path):
    with pytest.raises(ValidationError) as exc:
        await save(files={path: "text"})

    assert exc.value.code == "skill_file_path_invalid"


async def test_a_large_reference_file_is_refused(save):
    with pytest.raises(ValidationError) as exc:
        await save(files={"big.md": "x" * (config.MAX_FILE_CHARS + 1)})

    assert exc.value.code == "skill_file_too_long"


async def test_reference_files_have_a_total_limit(save):
    each = config.MAX_FILE_CHARS
    files = {f"part-{index}.md": "x" * each for index in range(config.MAX_FILES_TOTAL_CHARS // each + 1)}

    with pytest.raises(ValidationError) as exc:
        await save(files=files)

    assert exc.value.code == "skill_files_too_large"


@pytest.fixture
def run_import(organization_id):
    saved = []

    async def run(skills, existing_names=(), count=0):
        async def count_skills_fn(_organization_id):
            return count

        async def get_skill_fn(name, _organization_id):
            return object() if name in existing_names else None

        async def upsert_skill_fn(skill):
            saved.append(skill)
            return skill

        return await skills_use_cases.import_skills(
            organization_id=organization_id,
            skills=skills,
            created_by=uuid4(),
            count_skills_fn=count_skills_fn,
            get_skill_fn=get_skill_fn,
            upsert_skill_fn=upsert_skill_fn,
        )

    run.saved = saved
    return run


def _kit(*names: str) -> list:
    return [
        skills_use_cases.SkillImport(
            instructions=f"---\nname: {name}\ndescription: >\n  Does {name}.\n---\nSteps.",
            files={"brief.md": "Ten questions."},
        )
        for name in names
    ]


async def test_an_import_saves_every_skill_with_its_files(run_import):
    await run_import(_kit("landing-pages", "prompt-craft"))

    assert [skill.name for skill in run_import.saved] == ["landing-pages", "prompt-craft"]
    assert run_import.saved[0].description == "Does landing-pages."
    assert run_import.saved[0].files == {"brief.md": "Ten questions."}


async def test_one_bad_skill_stops_the_import_before_anything_is_saved(run_import):
    bad = skills_use_cases.SkillImport(instructions="---\nname: broken\n---\n")

    with pytest.raises(ValidationError) as exc:
        await run_import([*_kit("good-one"), bad])

    assert run_import.saved == []
    assert exc.value.message.startswith("broken: ")
    assert exc.value.code == "skill_instructions_missing"


async def test_an_import_naming_a_skill_twice_is_refused(run_import):
    with pytest.raises(ValidationError) as exc:
        await run_import(_kit("same", "same"))

    assert exc.value.code == "skill_import_duplicate"
    assert run_import.saved == []


async def test_an_import_counts_only_new_skills_against_the_limit(run_import):
    full = config.MAX_SKILLS_PER_ORGANIZATION

    await run_import(_kit("already-here"), existing_names={"already-here"}, count=full)
    assert len(run_import.saved) == 1

    with pytest.raises(ConflictError):
        await run_import(_kit("brand-new"), count=full)


async def test_an_empty_import_is_refused(run_import):
    with pytest.raises(ValidationError) as exc:
        await run_import([])

    assert exc.value.code == "skill_import_empty"
