"""Skills that show commands are told how to run them from their own text, not from their name."""

import pytest

from src.desktop import tools as desktop_tools
from src.knowledge import skill_notes

WITH_BLOCK = "# Check\n\nRun it:\n\n```bash\nnode render.js --in a.md\n```\n"
WITH_LINE = "Steps:\n\ngit fetch origin\ngit status\n"
PLAIN = "# Brand voice\n\nWrite with warmth. Use short sentences. Use the `git` tool? No.\n"


@pytest.mark.parametrize("text", [WITH_BLOCK, WITH_LINE, "```sh\nls\n```", "```PowerShell\nGet-ChildItem\n```", "$ npm test\n"])
def test_a_skill_that_shows_commands_is_recognised(text):
    assert skill_notes.uses_commands(text) is True


@pytest.mark.parametrize("text", [PLAIN, "", "```python\nprint(1)\n```", "We use github and gitlab a lot.", "Call the node of the tree."])
def test_prose_and_other_languages_are_not_taken_for_commands(text):
    assert skill_notes.uses_commands(text) is False


def test_any_skill_with_commands_gets_the_command_note_whatever_it_is_called():
    renamed = skill_notes.note_for("a-name-nobody-listed", WITH_BLOCK)

    assert skill_notes.COMMAND_NOTE in renamed
    assert "RunCommand" in renamed
    assert renamed.startswith(skill_notes.HEADER)


def test_a_skill_without_commands_gets_no_note_at_all():
    assert skill_notes.note_for("brand-voice", PLAIN) == ""


def test_a_skill_with_its_own_note_and_commands_gets_both_in_that_order():
    note = skill_notes.note_for("session-handoff", WITH_LINE)

    assert note.index("GitPush") < note.index(skill_notes.COMMAND_NOTE)


def test_the_name_alone_still_finds_a_specific_note():
    assert "GitStatus" in skill_notes.note_for("drift-check")


def test_the_note_tells_the_agent_where_commands_can_and_cannot_run():
    text = skill_notes.COMMAND_NOTE

    assert "only in the desktop app" in text
    assert "approves each one" in text
    assert "never claim to have run" in text
    assert "do not try to install" in text


def test_the_server_is_still_told_it_has_no_shell_and_where_the_one_that_exists_is():
    assert "RunCommand" in skill_notes.NO_SHELL
    assert "on the server" in skill_notes.NO_SHELL


def test_run_command_is_a_desktop_tool_that_always_asks_and_no_worker_gets():
    names = {schema.__name__ for schema in desktop_tools.SCHEMAS}
    tool = desktop_tools.build()["RunCommand"]

    assert "RunCommand" in names
    assert tool.requires_approval is True
    assert tool.always_ask is True
    assert tool.handler is None  # it runs on the user's computer, never here
