from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.tools.domain import Tool, truncate
from src.documents.sqlalchemy import adapter as documents_adapter
from src.projects.sqlalchemy import adapter as projects_adapter
from src.skills.sqlalchemy import adapter as skills_adapter

from . import config, context
from .schemas import ReadKnowledgeDocument, ReadSkill

UNKNOWN_DOCUMENT = (
    "No document with id '{document_id}' is available to this organization. "
    "Use only the ids listed in your context."
)

EMPTY_DOCUMENT = (
    "'{document_id}' has no readable text. Tell the user the document could not be "
    "read rather than guessing at its contents."
)

UNKNOWN_SKILL = (
    "No skill named '{name}' is available to this organization. "
    "Use only the names listed in your context."
)


def section(text: str, offset: int, size: int = config.MAX_TOOL_READ_CHARS) -> str:
    """One section of a document, cut at a paragraph or line break near its end where
    there is one, and saying where the next begins -- a brand book is far longer than one
    read, and its back half used to be silently out of reach."""
    total = len(text)
    if offset >= total:
        return f"[End of document: it has {total:,} characters; nothing from offset {offset:,} on.]"
    end = min(offset + size, total)
    if end < total:
        window = text[offset:end]
        cut = max(window.rfind("\n\n"), window.rfind("\n"))
        if cut > size // 2:
            end = offset + cut + 1
    body = text[offset:end]
    if offset == 0 and end == total:
        return body
    where = f"[Characters {offset:,}-{end:,} of {total:,}."
    after = f" Continue with offset={end}.]" if end < total else " This is the end.]"
    return f"{where}{after}\n\n{body}"


def build(session: AsyncSession, organization_id: UUID) -> dict[str, Tool]:
    async def read_knowledge_document(document_id: str, offset: int = 0) -> str:
        try:
            parsed = UUID(document_id)
        except ValueError:
            return UNKNOWN_DOCUMENT.format(document_id=document_id)

        text = await documents_adapter.get_text(session, parsed, organization_id)
        if text is None:
            document = await documents_adapter.get_for_organization(
                session, parsed, organization_id
            )
            if document is None:
                return UNKNOWN_DOCUMENT.format(document_id=document_id)
            return EMPTY_DOCUMENT.format(document_id=document_id)

        return section(text, offset)

    async def read_skill(name: str) -> str:
        skill = await skills_adapter.get_for_organization(session, name, organization_id)
        if skill is None:
            return UNKNOWN_SKILL.format(name=name)

        return truncate(skill.instructions, config.MAX_TOOL_READ_CHARS)

    return {
        ReadKnowledgeDocument.__name__: Tool(
            schema=ReadKnowledgeDocument, handler=read_knowledge_document
        ),
        ReadSkill.__name__: Tool(schema=ReadSkill, handler=read_skill),
    }


async def build_context(session: AsyncSession, organization_id: UUID) -> str:
    skills = await skills_adapter.list_for_organization(session, organization_id)
    documents = await documents_adapter.list_for_organization(session, organization_id)
    library = await projects_adapter.get_library(session, organization_id)
    listing = None
    if library is not None:
        tree = await projects_adapter.list_tree(session, library.id)
        listing = (library.name, context.library_paths(tree))
    return context.render(skills, documents, listing)
