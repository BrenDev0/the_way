import re

from src.assistants.catalog import server_tools
from src.background import tools as background_tools
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.desktop import tools as desktop_tools
from src.preferences import tools as preference_tools
from src.skills import tools as skill_tools

from .sqlalchemy import adapter
from .tool_schemas import SearchConversationHistory

STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "what", "when", "was", "were",
        "you", "your", "can", "did", "does", "have", "has", "had", "are", "about",
        "from", "not", "but", "all", "any", "how", "our", "out", "get", "let",
    }
)

# Candidates pulled from the database before ranking. Enough that a rare word still
# surfaces the right message; bounded so a common one cannot drag in the whole history.
CANDIDATES = 500
PREVIEW_CHARS = 400


def _words(text: str) -> set[str]:
    return {
        word.rstrip("s")
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    }


def build(context: ToolContext, desktop: bool) -> dict[str, Tool]:
    """Everything the conversation assistant can use this turn, for this user."""

    async def search_conversation_history(query: str, limit: int = 10) -> str:
        wanted = _words(query)
        if not wanted:
            return "Query had no searchable words. Use specific terms from what you are looking for."

        candidates = await adapter.search_messages(
            context.session, context.user_id, sorted(wanted), CANDIDATES
        )
        if not candidates:
            return f"Nothing in the saved conversations matches '{query}'."

        # rarer words are worth more: a term in half the messages barely narrows anything
        frequency: dict[str, int] = {}
        for message, _ in candidates:
            for word in _words(str(message.get("content", ""))):
                frequency[word] = frequency.get(word, 0) + 1

        scored = []
        for message, written_at in candidates:
            overlap = wanted & _words(str(message.get("content", "")))
            if overlap:
                scored.append((sum(1 / frequency[word] for word in overlap), written_at, message))

        scored.sort(key=lambda item: -item[0])
        lines = []
        for _, written_at, message in scored[:limit]:
            content = " ".join(str(message.get("content", "")).split())
            if len(content) > PREVIEW_CHARS:
                content = content[:PREVIEW_CHARS] + "..."
            lines.append(f"[{written_at:%Y-%m-%d %H:%M}] {message['role']}: {content}")
        return "\n".join(lines) or f"Nothing in the saved conversations matches '{query}'."

    tools = {
        **server_tools(context),
        **preference_tools.build(context),
        **skill_tools.build(context),
        **background_tools.build(context),
        SearchConversationHistory.__name__: Tool(
            schema=SearchConversationHistory, handler=search_conversation_history
        ),
    }
    if desktop:
        tools.update(desktop_tools.build())
    return tools
