from html import escape
from pathlib import Path

from .domain import Email

TEMPLATES = Path(__file__).parent / "email_templates"

VERIFICATION_EMAIL_SUBJECT = "Tu código de verificación · THE WAY"
INVITATION_EMAIL_SUBJECT = "Te invitaron a {organization} · THE WAY"

# As the panel names them (the_way_web, shared/session/store.ts).
ROLE_NAMES = {"owner": "propietario", "admin": "administrador", "member": "operador"}

# The app's pixel logo (the_way_web, shell Logo.tsx): each letter 5 x 5, one colour per row
# fading down. Drawn as table cells -- the one thing every mail client shows the same,
# Outlook included; most of them show no SVG.
_GLYPHS = {
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "H": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "E": ["#####", "#    ", "#### ", "#    ", "#####"],
    "W": ["#   #", "#   #", "# # #", "## ##", "#   #"],
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "Y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "],
}
_ROW_COLOURS = ["#00ff00", "#00d700", "#00af00", "#008700", "#005f00"]
_PIXEL = 4


def _logo(text: str = "THE WAY") -> str:
    rows = [""] * 5
    for index, char in enumerate(text):
        if char == " ":
            rows = [row + "  " for row in rows]
            continue
        for y in range(5):
            rows[y] += _GLYPHS[char][y] + (" " if index < len(text) - 1 else "")
    cells = []
    for y, row in enumerate(rows):
        filled = [
            f'<td width="{_PIXEL}" height="{_PIXEL}" bgcolor="{_ROW_COLOURS[y] if c == "#" else "#060a0e"}" '
            f'style="width:{_PIXEL}px;height:{_PIXEL}px;font-size:0;line-height:0;"></td>'
            for c in row
        ]
        cells.append("<tr>" + "".join(filled) + "</tr>")
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'aria-label="THE WAY" style="border-collapse:collapse;">' + "".join(cells) + "</table>"
    )


def _fill(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def _page(*, title: str, preheader: str, kicker: str, tag: str, content: str, footnote: str) -> str:
    """One of the app's terminal boxes, in a page every mail client renders. Every value
    is HTML already; callers escape what came from a user."""
    layout = (TEMPLATES / "layout.html").read_text(encoding="utf-8")
    return _fill(
        layout,
        {
            "title": title,
            "preheader": preheader,
            "logo": _logo(),
            "kicker": kicker,
            "tag": tag,
            "content": content,
            "footnote": footnote,
        },
    )


def create_verification_email(code: str, recipient_email: str) -> Email:
    content = _fill(
        (TEMPLATES / "verify_email.html").read_text(encoding="utf-8"),
        {"verification_code": escape(str(code))},
    )
    return Email(
        recipient=recipient_email,
        subject=VERIFICATION_EMAIL_SUBJECT,
        html_body=_page(
            title="Verifica tu correo",
            preheader=f"Tu código: {escape(str(code))}. Vence en 15 minutos.",
            kicker="consola de gestión :: acceso",
            tag="verificación",
            content=content,
            footnote="Recibes este correo porque alguien empezó a crear una cuenta con esta dirección.",
        ),
    )


def create_invitation_email(
    link: str,
    recipient_email: str,
    organization_name: str,
    role: str,
) -> Email:
    # The organization's name is whatever its owner typed: escaped, it is text in the
    # email, never markup -- not a link, a form or a hidden instruction.
    organization = escape(organization_name)
    content = _fill(
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
        html_body=_page(
            title="Invitación",
            preheader=f"{organization} te invitó a THE WAY.",
            kicker="consola de gestión :: invitación",
            tag="invitación",
            content=content,
            footnote="Recibes este correo porque alguien de la organización te invitó.",
        ),
    )
