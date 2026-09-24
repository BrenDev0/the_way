FENCE = "---"


def parse(content: str) -> tuple[str | None, str | None, str]:
    lines = content.replace("\r\n", "\n").split("\n")

    if not lines or lines[0].strip() != FENCE:
        return None, None, content.strip()

    name = description = None
    body_start = len(lines)

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            body_start = index + 1
            break
        stripped = line.strip()
        if stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("description:"):
            description = stripped.split(":", 1)[1].strip()

    return name or None, description or None, "\n".join(lines[body_start:]).strip()
