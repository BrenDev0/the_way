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
