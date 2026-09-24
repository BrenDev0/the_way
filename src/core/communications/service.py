from pathlib import Path

from .domain import Email

VERIFICATION_EMAIL_SUBJECT = "Verify your email"


def create_verification_email(code: str, recipient_email: str) -> Email:
    template_path = Path(__file__).parent / "email_templates" / "verify_email.html"

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    return Email(
        recipient=recipient_email,
        subject=VERIFICATION_EMAIL_SUBJECT,
        html_body=template.replace("{{verification_code}}", str(code)),
    )


INVITATION_EMAIL_SUBJECT = "You have been invited"


def create_invitation_email(
    link: str,
    recipient_email: str,
    organization_name: str,
    role: str,
) -> Email:
    template_path = Path(__file__).parent / "email_templates" / "invitation.html"

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    html_body = (
        template.replace("{{invitation_link}}", link)
        .replace("{{organization_name}}", organization_name)
        .replace("{{role}}", role)
    )

    return Email(
        recipient=recipient_email,
        subject=INVITATION_EMAIL_SUBJECT,
        html_body=html_body,
    )
