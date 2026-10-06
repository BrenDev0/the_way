from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from helpers import FakeLLM

from src.conversations import prompt, use_cases
from src.conversations.domain import Conversation, TurnState
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall

FIRST_EXCHANGE = [
    llm_domain.user("necesito un banner para la campaña de otoño"),
    llm_domain.assistant("", (ToolCall(id="c1", name="ListDir", args={}),)),
    llm_domain.tool_result("c1", "campanas/"),
    llm_domain.assistant([{"type": "text", "text": "Listo, creé el banner en campanas/otono."}]),
]


def conversation(title="Nueva conversación"):
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), title=title,
        turn=TurnState(), created_at=now, updated_at=now,
    )


class Renames:
    def __init__(self, current):
        self.current = current
        self.titles: list[str] = []

    async def __call__(self, conversation_id, title):
        self.titles.append(title)
        return replace(self.current, title=title)


async def test_a_placeholder_title_is_replaced_after_the_first_exchange():
    current = conversation()
    renames = Renames(current)
    llm = FakeLLM("Banner campaña de otoño")

    named = await use_cases.name_conversation(current, FIRST_EXCHANGE, llm, renames)

    assert named is not None and named.title == "Banner campaña de otoño"
    sent = llm.received[0]
    assert sent[0]["content"] == prompt.TITLE_SYSTEM
    # the user's words and the reply's words, not the tool traffic in between
    assert "campaña de otoño" in sent[1]["content"] and "Listo, creé el banner" in sent[1]["content"]
    assert "campanas/\n" not in sent[1]["content"]


async def test_a_title_someone_chose_is_kept():
    llm = FakeLLM("should not be asked")
    renames = Renames(conversation("Skill · coworking"))

    assert await use_cases.name_conversation(renames.current, FIRST_EXCHANGE, llm, renames) is None
    assert llm.received == [] and renames.titles == []


async def test_the_cut_off_first_message_the_app_used_as_a_title_is_replaced():
    # what the desktop app used to call a conversation started by typing
    current = conversation("necesito un banner para la campaña de oto")
    renames = Renames(current)

    named = await use_cases.name_conversation(current, FIRST_EXCHANGE, FakeLLM("Banner de otoño"), renames)

    assert named is not None and named.title == "Banner de otoño"


def test_a_title_is_unnamed_only_when_nobody_chose_it():
    assert use_cases.unnamed("Nueva conversación", FIRST_EXCHANGE)
    assert use_cases.unnamed("necesito un banner", FIRST_EXCHANGE)
    assert not use_cases.unnamed("Banner de otoño", FIRST_EXCHANGE)
    assert not use_cases.unnamed("Skill · coworking", FIRST_EXCHANGE)
    assert not use_cases.unnamed("  ", FIRST_EXCHANGE)


async def test_nothing_is_named_before_there_is_a_reply():
    llm = FakeLLM("should not be asked")
    renames = Renames(conversation())

    await use_cases.name_conversation(renames.current, [llm_domain.user("hola")], llm, renames)

    assert llm.received == []


async def test_the_model_answer_is_tidied_into_a_title():
    renames = Renames(conversation())

    await use_cases.name_conversation(
        renames.current, FIRST_EXCHANGE, FakeLLM('Title: "Banner de otoño".'), renames
    )

    assert renames.titles == ["Banner de otoño"]


async def test_a_long_answer_is_clipped():
    renames = Renames(conversation())

    await use_cases.name_conversation(renames.current, FIRST_EXCHANGE, FakeLLM("palabra " * 40), renames)

    assert len(renames.titles[0]) <= 60 and renames.titles[0].endswith("…")


async def test_an_empty_answer_leaves_the_placeholder():
    renames = Renames(conversation())

    assert await use_cases.name_conversation(renames.current, FIRST_EXCHANGE, FakeLLM("  "), renames) is None
    assert renames.titles == []
