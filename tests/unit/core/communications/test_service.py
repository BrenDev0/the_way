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
