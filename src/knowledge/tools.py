from uuid import UUID

from src.core.tools.domain import Tool
from src.documents.ports import (
    GetDocumentFn,
    GetDocumentTextFn,
    ListDocumentsForOrganizationFn,
)
from src.projects.ports import GetLibraryFn, ListTreeFn
from src.skills.ports import GetSkillFn, ListSkillsForOrganizationFn

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

UNKNOWN_SKILL_FILE = (
    "The skill '{name}' has no reference file '{file}'. Its files: {files}."
)

SKILL_FILES = (
    "\n\n---\nReference files of this skill. Read one with ReadSkill name='{name}' "
    "file='<path>' when the instructions send you to it:\n{files}"
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


def build(
    get_document_fn: GetDocumentFn,
    get_document_text_fn: GetDocumentTextFn,
    get_skill_fn: GetSkillFn,
    organization_id: UUID,
) -> dict[str, Tool]:
    async def read_knowledge_document(document_id: str, offset: int = 0) -> str:
        try:
            parsed = UUID(document_id)
        except ValueError:
            return UNKNOWN_DOCUMENT.format(document_id=document_id)

        text = await get_document_text_fn(parsed, organization_id)
        if text is None:
            document = await get_document_fn(parsed, organization_id)
            if document is None:
                return UNKNOWN_DOCUMENT.format(document_id=document_id)
            return EMPTY_DOCUMENT.format(document_id=document_id)

        return section(text, offset)

    async def read_skill(name: str, file: str | None = None, offset: int = 0) -> str:
        skill = await get_skill_fn(name, organization_id)
        if skill is None:
            return UNKNOWN_SKILL.format(name=name)

        files = skill.files or {}
        if file is not None:
            if file not in files:
                return UNKNOWN_SKILL_FILE.format(
                    name=name, file=file, files=", ".join(sorted(files)) or "none"
                )
            return section(files[file], offset)

        # A skill is a method to follow, so it is paged like a document rather than cut:
        # whatever lay past a cut was an instruction the agent never saw.
        text = skill.instructions
        if files:
            text += SKILL_FILES.format(name=name, files="\n".join(f"- {path}" for path in sorted(files)))
        return section(text, offset)

    return {
        ReadKnowledgeDocument.__name__: Tool(
            schema=ReadKnowledgeDocument, handler=read_knowledge_document
        ),
        ReadSkill.__name__: Tool(schema=ReadSkill, handler=read_skill),
    }


async def build_context(
    list_skills_fn: ListSkillsForOrganizationFn,
    list_documents_fn: ListDocumentsForOrganizationFn,
    get_library_fn: GetLibraryFn,
    list_tree_fn: ListTreeFn,
    organization_id: UUID,
) -> str:
    skills = await list_skills_fn(organization_id)
    documents = await list_documents_fn(organization_id)
    library = await get_library_fn(organization_id)
    listing = None
    if library is not None:
        tree = await list_tree_fn(library.id)
        listing = (library.name, context.library_paths(tree))
    return context.render(skills, documents, listing)
