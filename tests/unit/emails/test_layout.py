from src.auth import emails as auth_emails
from src.invitations import emails as invitation_emails


def test_both_emails_carry_the_apps_frame():
    for email in (
        auth_emails.create_verification_email("123456", "a@example.com"),
        invitation_emails.create_invitation_email(
            "https://x.example/i?t=1", "a@example.com", "Acme", "admin"
        ),
    ):
        assert 'aria-label="THE WAY"' in email.html_body  # the pixel logo
        assert "#060a0e" in email.html_body
        assert "{{" not in email.html_body
