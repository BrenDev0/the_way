from collections.abc import Sequence

from src.documents.domain import Document, DocumentStatus
from src.projects.domain import Folder, ProjectContents, ProjectFile
from src.skills.domain import Skill

from . import config

HEADER = "Organization knowledge available to you."

SKILLS_HEADER = (
    "Skills. Read the full instructions with ReadSkill before acting on one:"
)

DOCUMENTS_HEADER = (
    "Documents. Read one with ReadKnowledgeDocument, passing the id in brackets:"
)

MISSING_DESCRIPTION = "(no description)"

# Readable as soon as their text is out: waiting on someone to press "Entrenar" left a
# brand book uploaded and invisible.
READABLE = frozenset({DocumentStatus.EXTRACTED, DocumentStatus.TRAINED})

LIBRARY_HEADER = (
    "The organization's library -- project '{name}': logos, images and brand books that "
    "owners and admins uploaded, one folder per client brand. Use them; never change them "
    "(you cannot save there). On a page (BuildHtmlPage) or in an image tool (EditImage, "
    "OverlayImage, TransformImage...), name a file as project:{name}/<path>, e.g. "
    "project:{name}/{example}. When the request is about one brand, use only that brand's "
    "folder and documents -- never another client's logo or colours; if it is not clear "
    "which brand, ask. Files by folder:"
)
GENERAL = "(top level, not a brand)"


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _overflow(total: int, shown: int, noun: str) -> list[str]:
    if total <= shown:
        return []
    return [f"- ... and {total - shown} more {noun} not listed here."]


def library_paths(contents: ProjectContents) -> list[str]:
    """Every file in the library by its path, in folder order."""
    folders = {folder.id: folder for folder in contents.folders}

    def path_of(entry: Folder | ProjectFile) -> str:
        parts = [entry.name]
        parent = entry.parent_id if isinstance(entry, Folder) else entry.folder_id
        while parent is not None and parent in folders:
            parts.append(folders[parent].name)
            parent = folders[parent].parent_id
        return "/".join(reversed(parts))

    return sorted((path_of(file) for file in contents.files), key=str.lower)


def _library_lines(name: str, paths: Sequence[str]) -> list[str]:
    by_brand: dict[str, list[str]] = {}
    for path in paths:
        brand, _, rest = path.partition("/")
        if rest:
            by_brand.setdefault(brand, []).append(rest)
        else:
            by_brand.setdefault(GENERAL, []).append(path)

    example = paths[0] if paths else "Marca/logo.png"
    lines = ["", LIBRARY_HEADER.format(name=name, example=example)]
    brands = sorted(by_brand, key=lambda brand: (brand == GENERAL, brand.lower()))
    shown = brands[: config.MAX_LIBRARY_BRANDS]
    for brand in shown:
        files = by_brand[brand]
        listed = ", ".join(files[: config.MAX_LIBRARY_FILES_PER_BRAND])
        more = len(files) - config.MAX_LIBRARY_FILES_PER_BRAND
        label = brand if brand == GENERAL else f"{brand}/"
        tail = f" (+{more} more: ListProjectFolder '{name}' '{brand}')" if more > 0 else ""
        lines.append(f"- {label}: {listed}{tail}")
    lines += _overflow(len(brands), len(shown), "brand folders")
    return lines


def render(
    skills: Sequence[Skill],
    documents: Sequence[Document],
    library: tuple[str, Sequence[str]] | None = None,
) -> str:
    readable = [document for document in documents if document.status in READABLE]
    library_files = library[1] if library else []

    if not skills and not readable and not library_files:
        return ""

    lines = [HEADER]

    if skills:
        shown = list(skills)[: config.MAX_INDEX_ENTRIES]
        lines += ["", SKILLS_HEADER]
        lines += [
            f"- {skill.name}: "
            f"{_clip(skill.description, config.MAX_DESCRIPTION_CHARS) or MISSING_DESCRIPTION}"
            for skill in shown
        ]
        lines += _overflow(len(skills), len(shown), "skills")

    if readable:
        shown_documents = readable[: config.MAX_INDEX_ENTRIES]
        lines += ["", DOCUMENTS_HEADER]
        lines += [
            f"- [{document.id}] {document.title}"
            + (f" (brand: {document.brand})" if document.brand else "")
            + f": {_clip(document.description, config.MAX_DESCRIPTION_CHARS) or MISSING_DESCRIPTION}"
            for document in shown_documents
        ]
        lines += _overflow(len(readable), len(shown_documents), "documents")

    if library and library_files:
        lines += _library_lines(library[0], library_files)

    return "\n".join(lines)
