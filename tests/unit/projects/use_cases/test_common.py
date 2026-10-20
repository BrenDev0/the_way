
import pytest

from src.core.exceptions import ValidationError
from src.projects.use_cases import common as common_use_cases


@pytest.mark.parametrize("name", ["a", "Report 2026.pdf", "  padded  ", ".gitignore", "ñandú"])
def test_ordinary_names_are_accepted(name):
    assert common_use_cases.validate_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    ["", "   ", ".", "..", "trailing.", "a/b", "a\\b", "what?", "a:b", "tab\there", "x" * 256],
)
def test_names_windows_cannot_store_are_rejected(name):
    with pytest.raises(ValidationError) as exc:
        common_use_cases.validate_name(name)

    assert exc.value.code == "project_name_invalid"


@pytest.mark.parametrize("name", ["CON", "nul", "com1", "LPT9.txt", "aux.tar.gz"])
def test_windows_reserved_device_names_are_rejected(name):
    with pytest.raises(ValidationError):
        common_use_cases.validate_name(name)
