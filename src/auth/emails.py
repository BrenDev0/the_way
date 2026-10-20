from html import escape
from pathlib import Path

from src.core.communications.domain import Email
from src.emails import layout

TEMPLATES = Path(__file__).parent / "email_templates"

VERIFICATION_EMAIL_SUBJECT = "Tu código de verificación · THE WAY"


def create_verification_email(code: str, recipient_email: str) -> Email:
    content = layout.fill(
        (TEMPLATES / "verify_email.html").read_text(encoding="utf-8"),
        {"verification_code": escape(str(code))},
    )
    return Email(
        recipient=recipient_email,
        subject=VERIFICATION_EMAIL_SUBJECT,
        html_body=layout.page(
            title="Verifica tu correo",
            preheader=f"Tu código: {escape(str(code))}. Vence en 15 minutos.",
            kicker="consola de gestión :: acceso",
            tag="verificación",
            content=content,
            footnote="Recibes este correo porque alguien empezó a crear una cuenta con esta dirección.",
        ),
    )

