"""Checks that read the page's raw HTML -- what a browser does not show, and what a reading
by the model does not reliably catch.

- Notes left in HTML comments travel to production (Truth law: "the lexical gate reads raw
  HTML, not rendered text").
- A brand's voice.md names words that never appear in its public copy.
- A page made for one brand must carry nothing of another: its name, its library files,
  its signature colour (Truth law: "a template from another brand gets reused").

All of them are reported for the builder to fix, never fixed here: a forbidden word can be
allowed in context (SLS's "garantía" is, once a guarantee is sealed), and a comment can be
a deliberate conditional one.
"""

import html as html_lib
import re
from dataclasses import dataclass

_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
_INVISIBLE = re.compile(r"<(script|style|template|noscript)\b.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
# Text a person reads that is not between tags.
_READ_ATTRIBUTES = re.compile(
    r"""\b(?:alt|title|aria-label|placeholder|content)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")

# --- notes in comments -------------------------------------------------------------------


def comments(raw: str) -> list[str]:
    """Every HTML comment's text, but the browser-directive kind (<!--[if IE]>)."""
    found = []
    for match in _COMMENT.finditer(raw):
        body = " ".join(match.group(1).split())
        if not body or body.startswith(("[if", "<![endif]")):
            continue
        found.append(body)
    return found


# --- what the page says --------------------------------------------------------------------


def visible_text(raw: str) -> str:
    """The words a visitor can read: the text between tags and the attributes read out
    (alt, title, aria-label, placeholder, meta content) -- not scripts, styles or comments."""
    without = _INVISIBLE.sub(" ", _COMMENT.sub(" ", raw))
    attributes = " ".join(a or b for a, b in _READ_ATTRIBUTES.findall(without))
    return html_lib.unescape(" ".join((_TAG.sub(" ", without) + " " + attributes).split()))


def _term_pattern(term: str) -> re.Pattern[str]:
    # \b fails beside a non-word character ("{{ }}", "(muestra)"), so: no letter or digit
    # right before or after
    return re.compile(rf"(?<![\w]){re.escape(term)}(?![\w])", re.IGNORECASE)


def occurrences(text: str, terms: list[str]) -> dict[str, str]:
    """Each term found, with the words around its first appearance."""
    found = {}
    for term in terms:
        match = _term_pattern(term).search(text)
        if match:
            start, end = max(0, match.start() - 40), min(len(text), match.end() + 40)
            found[term] = ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
    return found


# --- forbidden words, out of voice.md ---------------------------------------------------------

_FORBIDDEN_HEADING = re.compile(
    r"^#+\s*(?:forbidden|prohibited|banned|words that never|never say|palabras prohibidas)", re.IGNORECASE
)
_HEADING = re.compile(r"^#+\s")
_QUOTED = re.compile(r"[\"“«]([^\"”»\n]{1,40})[\"”»]")
_CITATION = re.compile(r"\([^()]*(?:\.md|\.mjs|\.json|\.yaml|\.pdf)[^()]*\)")
_PARENTHETICAL = re.compile(r"\([^()]*\)")
_CLAUSE = re.compile(r"\s*(?:[;\n]|\.(?=\s|$))\s*")
_SPLIT = re.compile(r"\s*(?:[,:/]|—|–|\bor\b|\by\b|\bo\b|\band\b|\bsuch as\b|\blike\b)\s*", re.IGNORECASE)
_REPLACEMENT = re.compile(r"\b(?:say|di|use|usa|instead)\s*$", re.IGNORECASE)
_ENDS_THE_LIST = frozenset({"which", "that", "who", "que", "not", "never", "no"})
_SENTENCE_GOES_ON = frozenset({"must", "should", "may", "can", "never", "is", "are", "deben", "nunca"})

# A fragment starting with one of these is a phrase about the words, not a word.
_NOT_A_TERM = frozenset(
    ["a", "an", "and", "any", "also", "as", "avoid", "avoided", "be", "but", "by", "do", "does", "explicit", "for", "from", "in", "into", "is", "it", "its", "like", "may", "must", "never", "no", "not", "of", "on", "only", "or", "other", "say", "said", "see", "such", "that", "the", "their", "these", "this", "those", "to", "used", "use", "when", "which", "while", "with", "without", "words", "word", "language", "general", "public", "communication", "copy", "instead", "appear", "appears", "sample", "every", "visible", "ever", "allowed", "simply", "same", "outside", "unresolved"]
)


def forbidden_terms(voice_md: str | None) -> list[str]:
    """The words and phrases a brand's voice.md forbids, read out of its prose. Packs write
    the section as prose, not a list, so this keeps short fragments (one to three words)
    that are quoted or set in a list, and drops the phrases around them. An extra fragment
    costs nothing unless the page happens to say it; the finding then asks, not orders."""
    if not voice_md:
        return []
    section: list[str] = []
    inside = False
    for line in voice_md.splitlines():
        if _FORBIDDEN_HEADING.match(line):
            inside = True
            continue
        if inside and _HEADING.match(line):
            break
        if inside:
            section.append(line)
    body = "\n".join(section).strip()
    if not body or body.upper().startswith("N/A"):
        return []

    terms: list[str] = [
        match.group(1).strip(" ,.;")
        for match in _QUOTED.finditer(body)
        # 'say "a global network" instead' quotes the word to use, not the one to avoid
        if not _REPLACEMENT.search(body[max(0, match.start() - 12) : match.start()])
    ]
    plain = _PARENTHETICAL.sub(" ", _CITATION.sub(" ", body))
    plain = _QUOTED.sub(" , ", plain).replace("- ", "\n")
    for clause in _CLAUSE.split(plain):
        for fragment in _SPLIT.split(clause):
            words = fragment.strip(" .,'\"*-–—").split()
            if not words:
                continue
            first = words[0].lower()
            # "..., which never sells, quotes or pressures": what follows is no longer the list
            if first in _ENDS_THE_LIST:
                break
            # "..., or FIXME must never reach a page": the last item, then the sentence goes on
            cut = next((i for i, word in enumerate(words) if word.lower() in _SENTENCE_GOES_ON), None)
            if cut is not None and 1 <= cut <= 3 and first not in _NOT_A_TERM:
                terms.append(" ".join(words[:cut]))
                break
            if len(words) > 3 or first in _NOT_A_TERM:
                continue
            if any(char.isdigit() or char == "_" for char in fragment):
                continue
            terms.append(" ".join(words))

    unique: dict[str, str] = {}
    for term in terms:
        cleaned = term.strip()
        if len(cleaned) >= 2 and cleaned.lower() not in unique:
            unique[cleaned.lower()] = cleaned
    return list(unique.values())


# --- another brand's traces -------------------------------------------------------------------


@dataclass(frozen=True)
class OtherBrand:
    """What would give away that a page was made from another brand's: its names, its
    library folder, its signature colour."""

    folder: str
    names: tuple[str, ...]
    colours: tuple[str, ...] = ()


def brand_names(folder: str, identity_md: str | None) -> tuple[str, ...]:
    """The folder code and the names identity.md's title gives the brand: '# GRE (Gin Real
    Estate) — Identity' is GRE and Gin Real Estate."""
    names = [folder]
    title = next((line for line in (identity_md or "").splitlines() if line.startswith("# ")), "")
    title = re.split(r"\s+[—–-]\s+", title[2:], maxsplit=1)[0].strip()
    if title:
        names += [part.strip() for part in re.split(r"[()]", title) if len(part.strip()) >= 2]
    return tuple(dict.fromkeys(names))


def accent_colours(tokens_css: str | None) -> tuple[str, ...]:
    """A pack's signature colours: the values of its --brand and --brand-lift tokens."""
    found = re.findall(r"--brand(?:-lift)?\s*:\s*(#[0-9a-fA-F]{6})\b", tokens_css or "")
    return tuple(dict.fromkeys(colour.upper() for colour in found))


def other_brand_traces(raw: str, text: str, library: str, own_colours: set[str], others: list[OtherBrand]) -> list[str]:
    """Each trace of another brand: its name in the copy (matched case-sensitively, so
    the word 'exa' in a sentence is not the brand EXA), its library files, its colour."""
    page_colours = {colour.upper() for colour in _HEX.findall(raw)}
    traces = []
    for other in others:
        for name in other.names:
            if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text):
                traces.append(f"the name '{name}' ({other.folder}) appears in the copy")
        if f"project:{library}/{other.folder}/".lower() in raw.lower():
            traces.append(f"it uses files from {other.folder}'s library folder")
        for colour in other.colours:
            if colour in page_colours and colour not in own_colours:
                traces.append(f"{other.folder}'s signature colour {colour} is in the page")
    return traces
