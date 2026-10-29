"""What the staff routes accept. ApiBaseModel asks every string for two characters; the two
fields below need an exception, and these tests keep it from being forgotten."""

import pytest
from pydantic import ValidationError

from src.staff.fastapi.schemas import (
    CreateOwnerInvitationRequest,
    DeleteOrganizationRequest,
    StaffLoginRequest,
)


@pytest.mark.parametrize("password", ["a", "1", "x", "hunter", "a" * 72])
def test_a_staff_password_of_any_length_from_one_character_can_sign_in(password):
    """python -m src.staff.create accepts any non-empty password, so the sign-in must too:
    an account that can be made but never used is the worst of both."""
    assert StaffLoginRequest(email="ana@xplorers.example", password=password).password == password


def test_an_empty_staff_password_is_still_refused_at_the_door():
    with pytest.raises(ValidationError):
        StaffLoginRequest(email="ana@xplorers.example", password="")


@pytest.mark.parametrize("typed", ["", "A", "x", "Acme Inc", "a" * 255])
def test_the_confirmation_reaches_the_use_case_whatever_its_length(typed):
    """An organization named 'A' has to be deletable, and a blank answer has to be answered
    with the use case's own 'confirmation_mismatch', not a generic validation error."""
    assert DeleteOrganizationRequest(confirmation=typed).confirmation == typed


def test_the_confirmation_is_required():
    with pytest.raises(ValidationError):
        DeleteOrganizationRequest()  # type: ignore[call-arg]


def test_a_response_describing_stored_data_accepts_a_one_letter_name():
    """One organization named 'Z' (it cannot be made through the API, but can be in the
    database) must show up in the list, not make the whole list fail."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from src.staff.domain import OrganizationDeletion, OrganizationSummary
    from src.staff.fastapi.schemas import (
        OrganizationDeletionResponse,
        OrganizationSummaryResponse,
    )

    summary = OrganizationSummary(
        id=uuid4(), name="Z", seat_limit=None, created_at=datetime.now(UTC), members=0, pending_invitations=0,
        owner_encrypted_email=None, files=0, bytes=0, last_seen_at=None,
    )
    deletion = OrganizationDeletion(
        organization_name="Z", members=0, files=0, bytes=0, files_removed=0, files_left=0,
    )

    assert OrganizationSummaryResponse.from_domain(summary, owner_email=None).name == "Z"
    assert OrganizationDeletionResponse.from_domain(deletion).organization_name == "Z"


class FakeEncryption:
    def decrypt(self, value: str) -> str:
        if value.startswith("enc::"):
            return value.removeprefix("enc::")
        raise ValueError("not a token")


def test_a_readable_email_is_decrypted():
    from src.staff.fastapi.schemas import tolerant_decrypt

    assert tolerant_decrypt(FakeEncryption())("enc::ana@acme.mx") == "ana@acme.mx"


def test_an_email_that_cannot_be_decrypted_shows_a_placeholder_and_is_logged(caplog):
    """One damaged record must show as damaged, not turn the whole staff list into an error."""
    from src.staff.fastapi.schemas import UNREADABLE_EMAIL, tolerant_decrypt

    with caplog.at_level("WARNING"):
        shown = tolerant_decrypt(FakeEncryption())("garbage")

    assert shown == UNREADABLE_EMAIL == "(no se pudo leer)"
    assert "could not be decrypted" in caplog.text
    assert "garbage" not in caplog.text  # the value is never written to the log


def test_the_other_staff_fields_keep_the_shared_two_character_rule():
    """The exceptions are exactly those two; nothing else was loosened."""
    with pytest.raises(ValidationError):
        CreateOwnerInvitationRequest(organization_name="A", email="o@acme.example")
