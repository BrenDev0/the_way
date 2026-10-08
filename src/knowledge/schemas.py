from pydantic import BaseModel, Field


class ReadKnowledgeDocument(BaseModel):
    """Read one of the organization's documents, a section at a time.

    The id comes from the document listing in your context, written in brackets.
    Use this before answering anything that depends on the organization's own
    brand, policies, strategy or marketing material. A long document comes back in
    sections; the end of each says where the next one starts -- keep reading while
    what you need may still be ahead.
    """

    document_id: str = Field(description="The document id, exactly as listed in brackets")
    offset: int = Field(
        default=0, ge=0, description="Where to start, in characters: 0, then the offset the last section gave"
    )


class ReadSkill(BaseModel):
    """Read the full instructions for one of the organization's skills.

    The name comes from the skill listing in your context. Read the skill before
    acting on a request it covers, and follow its instructions.
    """

    name: str = Field(description="The skill name, exactly as listed")
