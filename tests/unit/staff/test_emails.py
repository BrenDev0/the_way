from src.staff import emails as staff_emails

LINK = "https://staff.example.com/accept-owner-invite?token=abc123"


def test_the_email_is_addressed_to_the_invitee_and_names_the_organization():
    email = staff_emails.create_owner_invitation_email(LINK, "owner@acme.example", "Acme Inc")

    assert email.recipient == "owner@acme.example"
    assert email.subject == "Crea Acme Inc en THE WAY"
    assert "Acme Inc" in email.html_body


def test_the_link_is_in_the_body_and_nothing_is_left_unfilled():
    email = staff_emails.create_owner_invitation_email(LINK, "owner@acme.example", "Acme Inc")

    assert LINK in email.html_body
    assert "{{" not in email.html_body


def test_a_name_with_a_line_break_cannot_end_the_subject_header():
    email = staff_emails.create_owner_invitation_email(LINK, "owner@acme.example", "Acme\r\nBcc: x@evil.example")

    assert "\n" not in email.subject
    assert "\r" not in email.subject
