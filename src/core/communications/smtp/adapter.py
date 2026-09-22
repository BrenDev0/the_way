import asyncio
import smtplib
from email.message import EmailMessage

from src.core.communications.domain import Email
from src.core.settings import settings


class SmtpEmailSender:
    async def send(self, email: Email) -> None:
        await asyncio.to_thread(self._send_blocking, email)

    def _send_blocking(self, email: Email) -> None:
        sender_address = settings.require_smtp_user()

        message = EmailMessage()
        message["From"] = sender_address
        message["To"] = email.recipient
        message["Subject"] = email.subject
        message.set_content(email.html_body, subtype="html")

        with smtplib.SMTP(settings.require_smtp_host(), settings.SMTP_PORT) as server:
            server.starttls()
            server.login(sender_address, settings.require_smtp_password())
            server.send_message(message)
