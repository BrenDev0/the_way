from collections.abc import Sequence

from src.documents.domain import Document, DocumentStatus
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


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _overflow(total: int, shown: int, noun: str) -> list[str]:
    if total <= shown:
        return []
    return [f"- ... and {total - shown} more {noun} not listed here."]


def render(skills: Sequence[Skill], documents: Sequence[Document]) -> str:
    readable = [
        document for document in documents if document.status is DocumentStatus.TRAINED
    ]

    if not skills and not readable:
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
            f"- [{document.id}] {document.title}: "
            f"{_clip(document.description, config.MAX_DESCRIPTION_CHARS) or MISSING_DESCRIPTION}"
            for document in shown_documents
        ]
        lines += _overflow(len(readable), len(shown_documents), "documents")

    return "\n".join(lines)
