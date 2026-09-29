from pydantic import BaseModel, Field


class SearchConversationHistory(BaseModel):
    """Search the user's previous conversations with you.

    Call this whenever the user refers to something discussed in another conversation
    that you cannot see -- "the report we did", "like we agreed", "the client from last
    week" -- or asks what was decided before. Prefer it over guessing: the earlier
    conversations are saved, not lost."""

    query: str = Field(
        description="Distinctive words from what you are looking for, for example "
        "'progreso landing page price' rather than 'the thing we discussed'"
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of messages to return")
