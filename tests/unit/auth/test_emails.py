from src.auth import emails as auth_emails


def test_addresses_and_subjects_the_email():
    email = auth_emails.create_verification_email("123456", "someone@example.com")

    assert email.recipient == "someone@example.com"
    assert email.subject == auth_emails.VERIFICATION_EMAIL_SUBJECT


def test_renders_the_code_into_the_template():
    email = auth_emails.create_verification_email("123456", "someone@example.com")

    assert "123456" in email.html_body
    assert "{{verification_code}}" not in email.html_body


def test_each_code_produces_its_own_body():
    first = auth_emails.create_verification_email("111111", "a@example.com")
    second = auth_emails.create_verification_email("222222", "a@example.com")

    assert first.html_body != second.html_body
    assert "222222" not in first.html_body
