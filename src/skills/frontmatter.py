import re
import textwrap
from typing import NamedTuple

FENCE = "---"

# A top-level "key: value" line. The key cannot hold a space or a colon, so a colon later
# in the value ("Use when: the user asks") stays part of the value.
KEY = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*:(.*)$")

# YAML block scalars: "description: >" folds the indented lines below into one line, and
# "description: |" keeps their line breaks. Skills written for other agents use both, and
# reading the marker itself as the value left every such skill described as ">".
FOLDED = frozenset({">", ">-", ">+"})
LITERAL = frozenset({"|", "|-", "|+"})


class Frontmatter(NamedTuple):
    name: str | None
    description: str | None
    body: str
    triggers: list[str]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _fold(lines: list[str]) -> str:
    """Lines join with a space; a blank line is a paragraph break."""
    paragraphs: list[list[str]] = [[]]
    for line in lines:
        if line.strip():
            paragraphs[-1].append(line.strip())
        elif paragraphs[-1]:
            paragraphs.append([])
    return "\n".join(" ".join(words) for words in paragraphs if words)


def _block_end(lines: list[str], index: int, indent: int) -> int:
    """Where the block below a key ends: every line indented deeper than the key, blanks
    included."""
    while index < len(lines) and (not lines[index].strip() or _indent(lines[index]) > indent):
        index += 1
    return index


def _list_items(lines: list[str]) -> list[str]:
    return [
        _unquote(line.strip()[1:].strip()) for line in lines if line.strip().startswith("-")
    ]


def _fields(lines: list[str]) -> dict[str, str | list[str]]:
    fields: dict[str, str | list[str]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        match = KEY.match(line)
        if match is None:
            continue

        key, value = match.group(1), match.group(2).strip()
        if value in FOLDED or value in LITERAL:
            end = _block_end(lines, index, _indent(line))
            block = lines[index:end]
            index = end
            if value in FOLDED:
                fields[key] = _fold(block)
            else:
                fields[key] = textwrap.dedent("\n".join(block)).strip()
        elif not value:
            # "triggers:" followed by "- item" lines is a list; YAML also allows the items
            # at the key's own indentation.
            end = index
            while end < len(lines) and (
                not lines[end].strip()
                or _indent(lines[end]) > _indent(line)
                or lines[end].strip().startswith("-")
            ):
                end += 1
            items = _list_items(lines[index:end])
            if items:
                index = end
            fields[key] = items if items else ""
        elif value.startswith("[") and value.endswith("]"):
            fields[key] = [
                _unquote(item.strip()) for item in value[1:-1].split(",") if item.strip()
            ]
        else:
            fields[key] = _unquote(value)
    return fields


def _text(value: str | list[str] | None) -> str | None:
    return value if isinstance(value, str) and value else None


def parse(content: str) -> Frontmatter:
    lines = content.replace("\r\n", "\n").split("\n")

    if not lines or lines[0].strip() != FENCE:
        return Frontmatter(None, None, content.strip(), [])

    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == FENCE),
        len(lines),
    )
    fields = _fields(lines[1:end])
    triggers = fields.get("triggers")

    return Frontmatter(
        name=_text(fields.get("name")),
        description=_text(fields.get("description")),
        body="\n".join(lines[end + 1 :]).strip(),
        triggers=triggers if isinstance(triggers, list) else [],
    )
