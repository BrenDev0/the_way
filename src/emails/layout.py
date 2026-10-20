"""The look every email of the app shares: its pixel logo and its framed page."""

from pathlib import Path

TEMPLATES = Path(__file__).parent

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


def logo(text: str = "THE WAY") -> str:
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


def fill(template: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def page(*, title: str, preheader: str, kicker: str, tag: str, content: str, footnote: str) -> str:
    """One of the app's terminal boxes, in a page every mail client renders. Every value
    is HTML already; callers escape what came from a user."""
    layout = (TEMPLATES / "layout.html").read_text(encoding="utf-8")
    return fill(
        layout,
        {
            "title": title,
            "preheader": preheader,
            "logo": logo(),
            "kicker": kicker,
            "tag": tag,
            "content": content,
            "footnote": footnote,
        },
    )
