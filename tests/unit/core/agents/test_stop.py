"""Stopping the loop at the user's request: between steps and while a reply is being written,
never in the middle of a tool, and always leaving a history a model accepts."""

import asyncio

from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import CUT_OFF, advance
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import Decision, Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate


class ReadFile(BaseModel):
    path: str


class Flag:
    """A stop that can be raised from the test, or after a number of looks."""

    def __init__(self, after: int | None = None) -> None:
        self.raised = False
        self.looks = 0
        self.after = after

    async def __call__(self) -> bool:
        self.looks += 1
        if self.after is not None and self.looks > self.after:
            self.raised = True
        return self.raised


async def read_file(path: str) -> str:
    return f"contents of {path}"


def executor():
    return Executor({"ReadFile": Tool(schema=ReadFile, handler=read_file)}, DenyGate())


def reading(call_id="c1"):
    return make_completion("", (ToolCall(id=call_id, name="ReadFile", args={"path": "a.txt"}),))


def start():
    return LoopState(messages=[llm_domain.user("do it")])


async def test_a_stop_before_the_first_model_call_calls_no_model():
    flag = Flag()
    flag.raised = True
    llm = FakeLLM("never said")

    result = await advance(start(), llm, executor(), should_stop=flag)

    assert result.status is LoopStatus.STOPPED
    assert llm.received == []
    assert [m["role"] for m in result.state.messages] == ["user"]


async def test_a_stop_after_a_tool_keeps_the_tool_and_its_result():
    # looks: before reply 1 (no), before reply 2 (yes)
    flag = Flag(after=1)
    llm = FakeLLM(reading(), "would have continued")

    result = await advance(start(), llm, executor(), should_stop=flag)

    assert result.status is LoopStatus.STOPPED
    assert [m["role"] for m in result.state.messages] == ["user", "assistant", "tool"]
    assert result.state.messages[-1]["content"] == "contents of a.txt"
    assert len(llm.received) == 1  # the second reply was never asked for


async def test_a_stop_while_a_reply_is_written_keeps_what_was_written_marked_as_cut_off():
    flag = Flag()

    class Slow:
        """Writes a few words, then the user stops it, then it would have written more."""

        async def respond(self, messages, tools=(), on_text=None):
            await on_text("Here is")
            await asyncio.sleep(0.5)  # longer than the poll: the next word is checked
            flag.raised = True
            await on_text(" the first part")
            raise AssertionError("the reply must not continue after the stop")

    result = await advance(start(), Slow(), executor(), should_stop=flag)

    assert result.status is LoopStatus.STOPPED
    last = result.state.messages[-1]
    assert last["role"] == "assistant"
    assert last["content"] == "Here is the first part" + CUT_OFF


async def test_a_reply_cut_off_before_any_word_leaves_no_empty_message():
    flag = Flag()

    class Silent:
        async def respond(self, messages, tools=(), on_text=None):
            flag.raised = True
            await asyncio.sleep(0.5)
            await on_text("late")
            raise AssertionError("must not get here")

    result = await advance(start(), Silent(), executor(), should_stop=flag)

    assert result.status is LoopStatus.STOPPED
    assert not any(m["role"] == "assistant" and not m.get("content") for m in result.state.messages)


async def test_calls_the_user_already_answered_are_settled_before_the_stop_lands():
    """A turn resumed after the user approved a call runs that call: it may already have run on
    their machine. The stop lands right after."""
    flag = Flag()
    flag.raised = True
    state = LoopState(
        messages=[llm_domain.user("do it"), llm_domain.assistant("", (ToolCall(id="c1", name="ReadFile", args={"path": "a.txt"}),))],
        pending_tool_calls=(ToolCall(id="c1", name="ReadFile", args={"path": "a.txt"}),),
    )
    llm = FakeLLM("never")

    result = await advance(state, llm, executor(), decisions={"c1": Decision(approved=True)}, should_stop=flag)

    assert result.status is LoopStatus.STOPPED
    assert [m["role"] for m in result.state.messages] == ["user", "assistant", "tool"]
    assert llm.received == []


async def test_without_a_stop_check_nothing_changes():
    result = await advance(start(), FakeLLM(reading(), "done"), executor())

    assert result.status is LoopStatus.COMPLETED
