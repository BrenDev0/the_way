import pytest
from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import advance, conversation_size
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import Decision, Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate, DenyGate


class ReadFile(BaseModel):
    path: str


class DeleteFile(BaseModel):
    path: str


async def read_file(path: str) -> str:
    return f"contents of {path}"


async def delete_file(path: str) -> str:
    return f"deleted {path}"


class SuspendingGate:
    async def decide(self, requests):
        from src.core.tools.domain import ApprovalRequired

        raise ApprovalRequired(tuple(requests))


TOOLS = {
    "ReadFile": Tool(schema=ReadFile, handler=read_file),
    "DeleteFile": Tool(schema=DeleteFile, handler=delete_file, requires_approval=True),
}


def executor(gate=None):
    return Executor(TOOLS, gate or DenyGate())


def call(name, call_id="c1", **args):
    return ToolCall(id=call_id, name=name, args=args)


def start(text="hello"):
    return LoopState(messages=[llm_domain.user(text)])


async def test_a_plain_answer_completes_in_one_iteration():
    llm = FakeLLM("the answer")

    result = await advance(start(), llm, executor())

    assert result.status is LoopStatus.COMPLETED
    assert result.text == "the answer"
    assert result.state.iterations_used == 1


async def test_the_assistant_message_is_appended():
    llm = FakeLLM("the answer")

    result = await advance(start(), llm, executor())

    assert result.state.messages[-1]["role"] == "assistant"


async def test_a_tool_call_then_an_answer():
    llm = FakeLLM(
        make_completion("", (call("ReadFile", path="x.txt"),)),
        make_completion("it says hello"),
    )

    result = await advance(start(), llm, executor())

    assert result.status is LoopStatus.COMPLETED
    assert result.text == "it says hello"
    assert result.state.iterations_used == 2


async def test_tool_results_are_appended_after_the_assistant_message():
    llm = FakeLLM(
        make_completion("", (call("ReadFile", path="x.txt"),)),
        make_completion("done"),
    )

    result = await advance(start(), llm, executor())

    roles = [m["role"] for m in result.state.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]


async def test_the_tool_message_carries_its_call_id():
    llm = FakeLLM(
        make_completion("", (call("ReadFile", "abc", path="x.txt"),)),
        make_completion("done"),
    )

    result = await advance(start(), llm, executor())

    tool_message = next(m for m in result.state.messages if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "abc"
    assert tool_message["content"] == "contents of x.txt"


async def test_an_empty_answer_with_no_tool_calls_still_completes():
    llm = FakeLLM(make_completion(""))

    result = await advance(start(), llm, executor())

    assert result.status is LoopStatus.COMPLETED
    assert result.text == ""


async def test_a_silent_tool_call_is_not_mistaken_for_an_answer():
    llm = FakeLLM(
        make_completion("", (call("ReadFile", path="x.txt"),)),
        make_completion("now I know"),
    )

    result = await advance(start(), llm, executor())

    assert result.status is LoopStatus.COMPLETED
    assert result.text == "now I know"


async def test_usage_accumulates_across_iterations():
    from src.core.llm.domain import TokenUsage

    llm = FakeLLM(
        make_completion("", (call("ReadFile", path="x"),), usage=TokenUsage(10, 5, 15)),
        make_completion("done", usage=TokenUsage(20, 3, 23)),
    )

    result = await advance(start(), llm, executor())

    assert result.state.usage == TokenUsage(30, 8, 38)


async def test_the_iteration_budget_is_enforced():
    llm = FakeLLM(*[make_completion("", (call("ReadFile", path="x"),)) for _ in range(5)])

    result = await advance(start(), llm, executor(), max_iterations=3)

    assert result.status is LoopStatus.ITERATION_LIMIT
    assert result.state.iterations_used == 3


async def test_a_resumed_run_continues_its_budget():
    llm = FakeLLM(make_completion("done"))
    state = LoopState(messages=[llm_domain.user("hi")], iterations_used=39)

    result = await advance(state, llm, executor(), max_iterations=40)

    assert result.status is LoopStatus.COMPLETED
    assert result.state.iterations_used == 40


async def test_a_gated_tool_suspends_the_run():
    llm = FakeLLM(make_completion("", (call("DeleteFile", path="x.txt"),)))

    result = await advance(start(), llm, executor(SuspendingGate()))

    assert result.status is LoopStatus.AWAITING_APPROVAL
    assert result.is_suspended


async def test_suspension_records_the_pending_call():
    llm = FakeLLM(make_completion("", (call("DeleteFile", "c9", path="x.txt"),)))

    result = await advance(start(), llm, executor(SuspendingGate()))

    assert [c.id for c in result.state.pending_tool_calls] == ["c9"]


async def test_suspension_keeps_the_assistant_message_so_resume_is_valid():
    llm = FakeLLM(make_completion("", (call("DeleteFile", path="x.txt"),)))

    result = await advance(start(), llm, executor(SuspendingGate()))

    assert result.state.messages[-1]["role"] == "assistant"
    assert result.state.messages[-1]["tool_calls"][0]["name"] == "DeleteFile"


async def test_resuming_with_an_approval_does_not_call_the_model_again():
    suspended = LoopState(
        messages=[llm_domain.user("hi"), llm_domain.assistant("", (call("DeleteFile", path="x"),))],
        pending_tool_calls=(call("DeleteFile", path="x"),),
        iterations_used=1,
    )
    llm = FakeLLM(make_completion("deleted it"))

    result = await advance(
        suspended, llm, executor(), decisions={"c1": Decision(approved=True)}
    )

    assert result.status is LoopStatus.COMPLETED
    assert len(llm.received) == 1


async def test_resuming_executes_the_approved_tool():
    suspended = LoopState(
        messages=[llm_domain.user("hi"), llm_domain.assistant("", (call("DeleteFile", path="x"),))],
        pending_tool_calls=(call("DeleteFile", path="x"),),
    )
    llm = FakeLLM(make_completion("done"))

    result = await advance(
        suspended, llm, executor(), decisions={"c1": Decision(approved=True)}
    )

    tool_message = next(m for m in result.state.messages if m["role"] == "tool")
    assert tool_message["content"] == "deleted x"


async def test_resuming_with_a_denial_tells_the_model_and_carries_on():
    suspended = LoopState(
        messages=[llm_domain.user("hi"), llm_domain.assistant("", (call("DeleteFile", path="x"),))],
        pending_tool_calls=(call("DeleteFile", path="x"),),
    )
    llm = FakeLLM(make_completion("understood"))

    result = await advance(
        suspended, llm, executor(), decisions={"c1": Decision(approved=False)}
    )

    tool_message = next(m for m in result.state.messages if m["role"] == "tool")
    assert "denied" in tool_message["content"]
    assert result.text == "understood"


async def test_ungated_work_in_a_gated_batch_is_not_thrown_away():
    calls = (
        call("ReadFile", "a", path="keep.txt"),
        call("DeleteFile", "b", path="gone.txt"),
    )
    llm = FakeLLM(make_completion("", calls))

    result = await advance(start(), llm, executor(SuspendingGate()))

    assert result.status is LoopStatus.AWAITING_APPROVAL
    assert [r.tool_call_id for r in result.state.completed_tool_results] == ["a"]
    assert [c.id for c in result.state.pending_tool_calls] == ["b"]


async def test_resuming_merges_the_earlier_ungated_results():
    calls = (
        call("ReadFile", "a", path="keep.txt"),
        call("DeleteFile", "b", path="gone.txt"),
    )
    llm = FakeLLM(make_completion("", calls), make_completion("all done"))

    suspended = await advance(start(), llm, executor(SuspendingGate()))
    resumed = await advance(
        suspended.state, llm, executor(), decisions={"b": Decision(approved=True)}
    )

    tool_ids = [m["tool_call_id"] for m in resumed.state.messages if m["role"] == "tool"]
    assert tool_ids == ["a", "b"]
    assert resumed.text == "all done"


async def test_an_auto_approve_gate_never_suspends():
    llm = FakeLLM(
        make_completion("", (call("DeleteFile", path="x.txt"),)),
        make_completion("done"),
    )

    result = await advance(start(), llm, executor(AutoApproveGate()))

    assert result.status is LoopStatus.COMPLETED


async def test_a_deny_gate_lets_the_model_carry_on():
    llm = FakeLLM(
        make_completion("", (call("DeleteFile", path="x.txt"),)),
        make_completion("I could not delete it"),
    )

    result = await advance(start(), llm, executor(DenyGate()))

    assert result.status is LoopStatus.COMPLETED
    assert result.text == "I could not delete it"


async def test_the_conversation_size_budget_stops_the_run():
    state = LoopState(messages=[llm_domain.user("x" * 500)])
    llm = FakeLLM("never reached")

    result = await advance(state, llm, executor(), max_conversation_chars=100)

    assert result.status is LoopStatus.CONVERSATION_LIMIT
    assert llm.received == []


async def test_conversation_size_counts_every_message():
    state = LoopState(messages=[llm_domain.user("abc"), llm_domain.assistant("de")])

    assert conversation_size(state) == 5


async def test_the_input_state_is_never_mutated():
    state = start()
    original = list(state.messages)
    llm = FakeLLM("done")

    await advance(state, llm, executor())

    assert state.messages == original


@pytest.mark.parametrize(
    "status",
    [LoopStatus.COMPLETED, LoopStatus.ITERATION_LIMIT, LoopStatus.CONVERSATION_LIMIT],
)
def test_only_awaiting_approval_counts_as_suspended(status):
    from src.core.agents.domain import LoopResult

    assert LoopResult(status=status, state=LoopState()).is_suspended is False


async def test_the_model_is_told_which_tools_exist():
    llm = FakeLLM(make_completion("done"))

    await advance(LoopState(messages=[llm_domain.user("hi")]), llm, Executor(TOOLS, DenyGate()))

    assert set(llm.tools_received[0]) == {ReadFile, DeleteFile}


async def test_an_empty_registry_binds_nothing():
    llm = FakeLLM(make_completion("done"))

    await advance(LoopState(messages=[llm_domain.user("hi")]), llm, Executor({}, DenyGate()))

    assert llm.tools_received[0] == ()
