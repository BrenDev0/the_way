from pydantic import BaseModel, Field


class ReadKnowledgeDocument(BaseModel):
    """Read the full text of one of the organization's documents.

    The id comes from the document listing in your context, written in brackets.
    Use this before answering anything that depends on the organization's own
    brand, policies, strategy or marketing material.
    """

    document_id: str = Field(description="The document id, exactly as listed in brackets")


class ReadSkill(BaseModel):
    """Read the full instructions for one of the organization's skills.

    The name comes from the skill listing in your context. Read the skill before
    acting on a request it covers, and follow its instructions.
    """

    name: str = Field(description="The skill name, exactly as listed")
