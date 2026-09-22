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
