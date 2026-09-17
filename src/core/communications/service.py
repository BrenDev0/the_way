import smtplib
from email.message import EmailMessage
from pathlib import Path

from src.core.settings import settings


def create_verification_email(code: str, recipient_email: str) -> EmailMessage:
    template_path = Path(__file__).parent / "email_templates" / "verify_email.html"

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    email_body = template.replace("{{verification_code}}", str(code))

    email_message = EmailMessage()
    email_message["From"] = settings.require_smtp_user()
    email_message["To"] = recipient_email
    email_message["Subject"] = "Verify your email"
    email_message.set_content(email_body, subtype="html")

    return email_message


def send_email(email_message: EmailMessage) -> None:
    with smtplib.SMTP(settings.require_smtp_host(), settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.require_smtp_user(), settings.require_smtp_password())
        server.send_message(email_message)
