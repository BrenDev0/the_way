from src.invitations import emails as invitation_emails
from src.staff import emails as staff_emails


def test_both_emails_carry_the_apps_frame():
    for email in (
        staff_emails.create_owner_invitation_email("https://x.example/o?t=1", "a@example.com", "Acme"),
        invitation_emails.create_invitation_email(
            "https://x.example/i?t=1", "a@example.com", "Acme", "admin"
        ),
    ):
        assert 'aria-label="THE WAY"' in email.html_body  # the pixel logo
        assert "#060a0e" in email.html_body
        assert "{{" not in email.html_body
