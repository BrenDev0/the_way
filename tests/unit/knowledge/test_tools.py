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


async def test_a_skill_is_read_exactly_as_its_author_wrote_it(read_skill):
    text = "Run `node engine/render.js <file>.html`, then `git push`."
    read_skill.stored["any-name"] = make_skill(name="any-name", instructions=text)

    assert await read_skill(name="any-name") == text


async def test_nothing_is_put_ahead_of_a_skill_whatever_it_is_called(read_skill):
    for name in ("output-documents", "landing-pages", "drift-check", "my-own-thing"):
        read_skill.stored[name] = make_skill(name=name, instructions="Do the thing.")

        assert await read_skill(name=name) == "Do the thing."


