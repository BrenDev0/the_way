from collections.abc import Sequence

from src.conversations import config, prompt
from src.conversations.domain import (
    Conversation,
)
from src.conversations.ports import (
    RenameConversationFn,
)
from src.core.llm import domain as llm_domain
from src.core.llm.domain import Message
from src.core.llm.ports import LLM


async def name_conversation(
    conversation: Conversation,
    history: Sequence[Message],
    llm: LLM,
    rename_fn: RenameConversationFn,
) -> Conversation | None:
    """Names a conversation after its first exchange, if nobody named it (unnamed) and it
    has one: a user message and a reply to it. None when nothing changed."""
    exchange = _first_exchange(history)
    if exchange is None or not unnamed(conversation.title, history):
        return None

    user_text, assistant_text = exchange
    completion = await llm.respond([
        llm_domain.system(prompt.TITLE_SYSTEM),
        llm_domain.user(
            prompt.TITLE_USER.format(
                user=user_text[: config.TITLE_EXCERPT_CHARS],
                assistant=assistant_text[: config.TITLE_EXCERPT_CHARS],
            )
        ),
    ])
    title = _clean_title(completion.text)
    if not title or title in config.PLACEHOLDER_TITLES:
        return None
    return await rename_fn(conversation.id, title)


def unnamed(title: str, history: Sequence[Message]) -> bool:
    """Whether a conversation's title is one nobody chose: a placeholder, or the opening
    words of its first message -- what the desktop app used to call a conversation started
    by typing in an empty chat, which then kept that cut-off sentence for good."""
    if title in config.PLACEHOLDER_TITLES:
        return True
    start = title.strip()
    first = next((_text(m.get("content")) for m in history if m.get("role") == "user"), "")
    return bool(start) and first.startswith(start)


def _text(content: object) -> str:
    """A message's words: OpenAI stores a string, Anthropic a list of typed blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) for block in content
            if isinstance(block, dict) and block.get("type") in (None, "text")
        ).strip()
    return ""


def _first_exchange(history: Sequence[Message]) -> tuple[str, str] | None:
    """The user's first message and the first reply with words in it, after it."""
    user_text = ""
    for message in history:
        role = message.get("role")
        if role == "user" and not user_text:
            user_text = _text(message.get("content"))
        elif role == "assistant" and user_text and (reply := _text(message.get("content"))):
            return user_text, reply
    return None


def _clean_title(text: str) -> str:
    title = " ".join(text.split())
    for prefix in ("Title:", "Título:"):
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix):]
    # quotes and a final period in either order -- '"Banner".' as well as '"Banner."'
    title = title.strip().rstrip(".").strip("\"'`*#« »“”").rstrip(".").strip()
    if len(title) > config.MAX_TITLE_CHARS:
        title = title[: config.MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title
