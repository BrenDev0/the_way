"""Page selections as people write them: "1-3, 5, 8-", "2", "all", "last"."""


class PageSpecError(ValueError):
    pass


def parse_pages(spec: str | None, count: int) -> list[int]:
    """Zero-based page indexes in the order written. Ranges may run backwards ("5-1"), an
    open end means the last page ("8-"), and "last" names it. Empty or "all" is every page."""
    text = (spec or "").strip().lower()
    if text in ("", "all", "todas", "todo"):
        return list(range(count))

    def number(part: str) -> int:
        part = part.strip()
        if part in ("last", "ultima", "última"):
            return count
        if not part.isdigit():
            raise PageSpecError(f"'{part}' is not a page number")
        value = int(part)
        if not 1 <= value <= count:
            raise PageSpecError(f"page {value} does not exist; the document has {count}")
        return value

    pages: list[int] = []
    for piece in text.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            start_text, end_text = piece.split("-", 1)
            start = number(start_text) if start_text.strip() else 1
            end = number(end_text) if end_text.strip() else count
            step = 1 if end >= start else -1
            pages.extend(range(start - 1, end - 1 + step, step))
        else:
            pages.append(number(piece) - 1)
    if not pages:
        raise PageSpecError(f"'{spec}' selects no pages")
    return pages
