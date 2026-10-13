from src.core.communications import service as communications_service


def test_addresses_and_subjects_the_email():
    email = communications_service.create_verification_email("123456", "someone@example.com")

    assert email.recipient == "someone@example.com"
    assert email.subject == communications_service.VERIFICATION_EMAIL_SUBJECT


def test_renders_the_code_into_the_template():
    email = communications_service.create_verification_email("123456", "someone@example.com")

    assert "123456" in email.html_body
    assert "{{verification_code}}" not in email.html_body


def test_each_code_produces_its_own_body():
    first = communications_service.create_verification_email("111111", "a@example.com")
    second = communications_service.create_verification_email("222222", "a@example.com")

    assert first.html_body != second.html_body
    assert "222222" not in first.html_body


def test_the_invitation_shows_the_organization_as_text_never_markup():
    email = communications_service.create_invitation_email(
        link="https://app.example.com/accept-invite?token=abc&x=1",
        recipient_email="new@example.com",
        organization_name='Acme <a href="https://evil.example">gana</a>',
        role="member",
    )

    assert "<a href=\"https://evil.example\">" not in email.html_body
    assert "Acme &lt;a href=" in email.html_body
    assert 'href="https://app.example.com/accept-invite?token=abc&amp;x=1"' in email.html_body
    assert "operador" in email.html_body  # the role as the panel names it
    assert "{{" not in email.html_body


def test_both_emails_carry_the_apps_frame():
    for email in (
        communications_service.create_verification_email("123456", "a@example.com"),
        communications_service.create_invitation_email("https://x.example/i?t=1", "a@example.com", "Acme", "admin"),
    ):
        assert 'aria-label="THE WAY"' in email.html_body  # the pixel logo
        assert "#060a0e" in email.html_body
        assert "{{" not in email.html_body
