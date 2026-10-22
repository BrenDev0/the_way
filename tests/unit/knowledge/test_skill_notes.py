import pytest

from src.desktop import tools as desktop_tools
from src.knowledge import skill_notes


@pytest.mark.parametrize("name", ["drift-check", "session-handoff"])
def test_the_git_skills_run_through_the_git_tools(name):
    note = skill_notes.note_for(name)

    assert "depends on git; tell the user it cannot run here" not in note  # they were given up on
    for tool in ("GitStatus", "GitFetch"):
        assert tool in note


def test_every_git_tool_the_notes_name_exists_in_the_catalog():
    names = {schema.__name__ for schema in desktop_tools.GIT}
    for skill in ("drift-check", "session-handoff"):
        mentioned = {word.strip(".,:;()`") for word in skill_notes.note_for(skill).split()}
        assert {word for word in mentioned if word.startswith("Git") and word != "Git"} <= names


def test_the_notes_tell_the_agent_that_git_setup_is_the_users_and_never_ask_for_secrets():
    note = skill_notes.note_for("session-handoff")

    assert "password or token" in note
    assert "not on the desktop app" in note


def test_a_push_the_remote_refuses_is_never_worked_around():
    assert "cannot pull or merge" in skill_notes.note_for("session-handoff")


def test_git_has_no_command_that_can_destroy_work():
    names = {schema.__name__.lower() for schema in desktop_tools.GIT}

    assert not names & {"gitreset", "gitclean", "gitcheckout", "gitrun", "gitforcepush"}
    assert not any("force" in field for schema in desktop_tools.GIT for field in schema.model_fields)
