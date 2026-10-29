from helpers import make_skill

from src.html_pages import config, skill


def test_the_skill_and_its_reference_files_reach_the_builder():
    text = skill.render(
        make_skill(
            name="landing-pages",
            instructions="0 Brief, 1 Structure.",
            files={"laws.md": "# Laws\nEvery figure attributed.", "brief.md": "# Ten questions"},
        )
    )

    assert text.startswith("=== SKILL: landing-pages")
    assert "0 Brief, 1 Structure." in text
    assert "--- landing-pages/brief.md ---\n# Ten questions" in text
    assert "Every figure attributed." in text
    # the skill is the customer's: nothing is added to it, whatever it is called
    assert "RUNNING THIS SKILL HERE" not in text


def test_a_program_among_the_files_is_named_not_sent():
    text = skill.render(
        make_skill(
            name="output-documents",
            files={"engine/core.css": ":root{}", "engine/render.js": "const chrome = require('x')"},
        )
    )

    assert "--- output-documents/engine/core.css ---" in text
    assert "require('x')" not in text
    assert "Not included (over the budget, or a program the page cannot use): engine/render.js." in text


def test_files_past_the_budget_are_named_not_cut():
    big = "x" * config.MAX_SKILL_CHARS
    text = skill.render(make_skill(name="big", files={"a.md": "small", "b.md": big}))

    assert "--- big/a.md ---" in text
    assert big not in text
    assert "b.md" in text.split("Not included")[1]
