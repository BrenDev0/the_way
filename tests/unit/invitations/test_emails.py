from src.invitations import emails as invitation_emails


def test_the_invitation_shows_the_organization_as_text_never_markup():
    email = invitation_emails.create_invitation_email(
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
