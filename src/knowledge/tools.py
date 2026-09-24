from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.tools.domain import Tool, truncate
from src.documents.sqlalchemy import adapter as documents_adapter
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


def build(session: AsyncSession, organization_id: UUID) -> dict[str, Tool]:
    async def read_knowledge_document(document_id: str) -> str:
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

        return truncate(text, config.MAX_TOOL_READ_CHARS)

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
    return context.render(skills, documents)
