"""A brand pack, put into the house's own terms.

A pack (one folder per brand in the organization's library: tokens.css, identity.md,
voice.md, logo/) names its tokens its own way, and one of those names collides with ours:
a pack's --ink is the dark ground of an inverted band, the house's --ink is body text.
Left to the model, that mapping is a guess made again on every page. Here it is made once,
from the names every pack shares, and a role the pack does not fill is said to be missing
rather than invented.
"""

import re

from . import config

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECLARATION = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+);")
_REFERENCE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)")

# House role <- the pack tokens that fill it, first match wins.
COLOUR_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("--ground", ("--paper",)),
    ("--surface", ("--surface",)),
    ("--ink", ("--fg",)),
    ("--ink-muted", ("--fg-2",)),
    ("--ink-faint", ("--fg-3",)),
    ("--line", ("--line",)),
    ("--accent", ("--brand",)),
    ("--accent-soft", ("--brand-dim", "--tint")),
    ("--radius", ("--r",)),
)

FONT_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Headings", ("--font-dsp", "--family-display")),
    ("Body", ("--font-bdy", "--family-body")),
    ("Figures and labels", ("--font-mn", "--family-mono")),
)

DARK_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Dark band ground", ("--ink",)),
    ("Text on the dark band", ("--fg-inv",)),
    ("Muted text on the dark band", ("--fg-inv-2",)),
)


def parse_tokens(css: str) -> dict[str, str]:
    """Every custom property in the file, later declarations winning, with var()
    references resolved -- the pack's engine block aliases one token to another."""
    raw = {name: value.strip() for name, value in _DECLARATION.findall(_COMMENT.sub("", css))}

    def resolve(value: str, depth: int = 0) -> str:
        if depth > 5:
            return value

        def substitute(match: re.Match[str]) -> str:
            target = raw.get(match.group(1))
            if target is not None:
                return resolve(target, depth + 1)
            return (match.group(2) or match.group(0)).strip()

        return _REFERENCE.sub(substitute, value)

    return {name: resolve(value) for name, value in raw.items()}


def _first(tokens: dict[str, str], names: tuple[str, ...]) -> str | None:
    return next((tokens[name] for name in names if tokens.get(name)), None)


def house_tokens(tokens: dict[str, str]) -> tuple[list[str], list[str]]:
    """The :root lines this brand fills, and the house roles it leaves to the defaults."""
    lines: list[str] = []
    missing: list[str] = []
    for role, names in COLOUR_ROLES:
        value = _first(tokens, names)
        if value is None:
            missing.append(role)
        else:
            lines.append(f"  {role}: {value};")
    return lines, missing


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= config.MAX_BRAND_FILE_CHARS:
        return text
    return text[: config.MAX_BRAND_FILE_CHARS].rstrip() + "\n[... cut here; the rest is in the pack]"


def render(
    brand: str,
    library: str,
    tokens_css: str,
    identity: str | None,
    voice: str | None,
    logos: list[str],
) -> str:
    tokens = parse_tokens(tokens_css)
    lines, missing = house_tokens(tokens)

    sections = [
        f"=== BRAND PACK: {brand} (binding) ===",
        (
            "This page is for this brand. Its values replace the house palette and typefaces "
            "on every point below; the house system still governs space, scale, hierarchy and "
            "detail. Use the values exactly. Never invent one the pack does not give."
        ),
        "",
        "House tokens, from the pack:",
        ":root {",
        *lines,
        "}",
    ]
    if missing:
        sections.append(
            f"Not in the pack, so the house default stands: {', '.join(missing)}."
        )

    fonts = [(role, _first(tokens, names)) for role, names in FONT_ROLES]
    sections += ["", "Typefaces:"]
    sections += [f"- {role}: {value or 'not in the pack -- use the house default'}" for role, value in fonts]
    sections.append(
        "Load them from Google Fonts by family name; the pack ships no font files."
    )

    dark = [(role, _first(tokens, names)) for role, names in DARK_ROLES]
    if any(value for _role, value in dark):
        sections += ["", "For an inverted (dark) band -- note the pack's --ink is this ground, not text:"]
        sections += [f"- {role}: {value}" for role, value in dark if value]

    if logos:
        sections += [
            "",
            (
                "Logos -- the brand's own files; use one only as an image, never redraw it. "
                "identity.md says which variant goes on which ground:"
            ),
        ]
        sections += [f"- project:{library}/{path}" for path in logos]
    else:
        sections += ["", "The pack has no logo file. Do not draw one; set the brand name as text."]

    if identity:
        sections += ["", "--- identity.md ---", _clip(identity)]
    if voice:
        sections += [
            "",
            "--- voice.md (the words on the page follow it; its forbidden words never appear) ---",
            _clip(voice),
        ]
    return "\n".join(sections)
