from html import escape
from pathlib import Path

from src.core.communications.domain import Email
from src.emails import layout

TEMPLATES = Path(__file__).parent / "email_templates"

OWNER_INVITATION_EMAIL_SUBJECT = "Crea {organization} en THE WAY"


def create_owner_invitation_email(
    link: str,
    recipient_email: str,
    organization_name: str,
) -> Email:
    # The organization's name is whatever we typed, but it is still text in the email,
    # never markup.
    organization = escape(organization_name)
    content = layout.fill(
        (TEMPLATES / "owner_invitation.html").read_text(encoding="utf-8"),
        {
            "organization_name": organization,
            "invitation_link": escape(link, quote=True),
        },
    )
    return Email(
        recipient=recipient_email,
        # one line: a line break in a header would end it and start another
        subject=OWNER_INVITATION_EMAIL_SUBJECT.format(organization=" ".join(organization_name.split())),
        html_body=layout.page(
            title="Invitación",
            preheader=f"Xplorers te invita a abrir {organization} en THE WAY.",
            kicker="consola de gestión :: invitación",
            tag="invitación",
            content=content,
            footnote="Recibes este correo porque Xplorers te invitó a abrir una organización.",
        ),
    )
