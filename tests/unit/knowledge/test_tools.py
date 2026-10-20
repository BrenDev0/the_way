from uuid import uuid4

import pytest
from helpers import make_skill

from src.knowledge import config, tools


@pytest.fixture
def read_skill():
    stored = {}

    async def get_skill(name, _organization_id):
        return stored.get(name)

    async def unused(*_args):
        raise AssertionError("reading a skill touches no document")

    handler = tools.build(
        get_document_fn=unused,
        get_document_text_fn=unused,
        get_skill_fn=get_skill,
        organization_id=uuid4(),
    )["ReadSkill"].handler
    handler.stored = stored
    return handler


async def test_a_short_skill_comes_back_whole(read_skill):
    read_skill.stored["brand-voice"] = make_skill()

    assert await read_skill(name="brand-voice") == "1. Be warm.\n2. Be plain."


async def test_a_long_skill_is_paged_rather_than_cut(read_skill):
    text = "\n".join(f"Step {index}: do the thing properly." for index in range(2_000))
    read_skill.stored["long"] = make_skill(name="long", instructions=text)

    assert len(text) > config.MAX_TOOL_READ_CHARS
    pages = [await read_skill(name="long")]
    while "Continue with offset=" in pages[-1]:
        offset = int(pages[-1].split("Continue with offset=")[1].split(".]")[0])
        pages.append(await read_skill(name="long", offset=offset))

    assert len(pages) > 1
    assert "Step 1999" in pages[-1]
    assert "This is the end." in pages[-1]


async def test_a_skill_lists_its_reference_files(read_skill):
    read_skill.stored["landing-pages"] = make_skill(
        name="landing-pages", files={"laws.md": "# Laws", "brief.md": "# Brief"}
    )

    text = await read_skill(name="landing-pages")

    assert "- brief.md\n- laws.md" in text
    assert "file='<path>'" in text


async def test_a_reference_file_is_read_by_its_path(read_skill):
    read_skill.stored["landing-pages"] = make_skill(name="landing-pages", files={"laws.md": "# Laws"})

    assert await read_skill(name="landing-pages", file="laws.md") == "# Laws"


async def test_an_unknown_reference_file_names_the_ones_that_exist(read_skill):
    read_skill.stored["landing-pages"] = make_skill(name="landing-pages", files={"laws.md": "# Laws"})

    text = await read_skill(name="landing-pages", file="secrets.md")

    assert "no reference file 'secrets.md'" in text
    assert "laws.md" in text


async def test_an_unknown_skill_is_reported(read_skill):
    assert "No skill named 'nope'" in await read_skill(name="nope")


async def test_a_skill_written_for_a_shell_says_first_how_it_runs_here(read_skill):
    read_skill.stored["output-documents"] = make_skill(
        name="output-documents", instructions="Run `node engine/render.js <file>.html`."
    )

    text = await read_skill(name="output-documents")

    # the note comes ahead of the skill, so it is on the first page of a long one
    assert text.index("RUNNING THIS SKILL HERE") < text.index("node engine/render.js")
    assert "HtmlToPdf" in text


async def test_a_skill_that_runs_as_written_gets_no_note(read_skill):
    read_skill.stored["brand-voice"] = make_skill()

    assert "RUNNING THIS SKILL HERE" not in await read_skill(name="brand-voice")


async def test_a_brand_landing_page_reads_the_pack_before_asking_and_flags_the_request(read_skill):
    read_skill.stored["landing-pages"] = make_skill(name="landing-pages", instructions="0 Brief.")

    text = await read_skill(name="landing-pages")
    note = text.split("=== THE SKILL")[0]

    assert "<brand>/voice.md" in note and "BEFORE asking" in note
    assert "forbids" in note and "another library brand's name" in note
