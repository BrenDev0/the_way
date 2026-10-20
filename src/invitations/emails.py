from html import escape
from pathlib import Path

from src.core.communications.domain import Email
from src.emails import layout

TEMPLATES = Path(__file__).parent / "email_templates"

INVITATION_EMAIL_SUBJECT = "Te invitaron a {organization} · THE WAY"

# As the panel names them (the_way_web, shared/session/store.ts).
ROLE_NAMES = {"owner": "propietario", "admin": "administrador", "member": "operador"}


def create_invitation_email(
    link: str,
    recipient_email: str,
    organization_name: str,
    role: str,
) -> Email:
    # The organization's name is whatever its owner typed: escaped, it is text in the
    # email, never markup -- not a link, a form or a hidden instruction.
    organization = escape(organization_name)
    content = layout.fill(
        (TEMPLATES / "invitation.html").read_text(encoding="utf-8"),
        {
            "organization_name": organization,
            "role": escape(ROLE_NAMES.get(role, role)),
            "invitation_link": escape(link, quote=True),
        },
    )
    return Email(
        recipient=recipient_email,
        # one line: a line break in a header would end it and start another
        subject=INVITATION_EMAIL_SUBJECT.format(organization=" ".join(organization_name.split())),
        html_body=layout.page(
            title="Invitación",
            preheader=f"{organization} te invitó a THE WAY.",
            kicker="consola de gestión :: invitación",
            tag="invitación",
            content=content,
            footnote="Recibes este correo porque alguien de la organización te invitó.",
        ),
    )
