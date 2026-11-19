from src.conversations import prompt
from src.desktop import tools as desktop_tools

COMPUTER = {
    "RequestComputerAccess",
    "ListComputerFolder",
    "SearchComputer",
    "SearchComputerText",
    "ReadComputerFile",
}


def test_the_computer_tools_are_offered_to_the_desktop():
    assert COMPUTER <= set(desktop_tools.build())


def test_only_the_access_request_asks_and_it_asks_every_time():
    built = desktop_tools.build()

    assert built["RequestComputerAccess"].requires_approval
    assert built["RequestComputerAccess"].always_ask
    for name in COMPUTER - {"RequestComputerAccess"}:
        assert not built[name].requires_approval
        assert not built[name].always_ask


def test_no_computer_tool_changes_anything():
    writers = ("Write", "Create", "Update", "Delete", "Move", "Rename", "Copy", "Edit")

    assert not [name for name in COMPUTER if name.startswith(writers)]


def test_the_agent_is_told_how_to_use_them():
    assert "RequestComputerAccess" in prompt.SYSTEM
    assert "READ ONLY" in prompt.SYSTEM


def test_the_per_turn_note_never_sends_the_user_to_pick_a_folder_to_find_a_file():
    notes = {
        "no folder open": prompt._local_folder_line(""),
        "a folder open": prompt._local_folder_line("C:/Users/ana/Documents"),
        "a project open": prompt._remote_folder_line("Borradores/informes"),
    }

    for name, note in notes.items():
        assert "RequestComputerAccess" in note, name
        assert "SearchComputer" in note, name
        assert "NEVER ask them to pick a folder" in note, name
        assert "out of reach" not in note, name


def test_with_no_folder_open_the_note_does_not_say_the_agent_is_blind():
    note = prompt._local_folder_line("")

    assert "does NOT stop you finding files" in note
    assert "do not need any folder to be open" in note


def test_the_local_search_tool_says_it_only_sees_the_open_folder():
    from src.desktop.schemas import SearchFile

    assert "INSIDE THE FOLDER THE USER HAS OPEN" in SearchFile.__doc__
    assert "SearchComputer" in SearchFile.__doc__
