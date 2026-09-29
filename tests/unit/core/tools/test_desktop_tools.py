import pytest
from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.core.agents.domain import LoopState, LoopStatus
from src.core.agents.loop import advance
from src.core.agents.runner import run_assistant
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import (
    NO_DESKTOP,
    ClientActionRequired,
    Decision,
    Tool,
    ToolLocation,
)
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate, DenyGate, SuspendGate


class ReadFile(BaseModel):
    file_path: str


class DeleteFile(BaseModel):
    file_path: str


class ListProjects(BaseModel):
    pass


async def list_projects() -> str:
    return "Website"


TOOLS = {
    "ReadFile": Tool(schema=ReadFile, location=ToolLocation.DESKTOP),
    "DeleteFile": Tool(schema=DeleteFile, location=ToolLocation.DESKTOP, requires_approval=True),
    "ListProjects": Tool(schema=ListProjects, handler=list_projects),
}


def call(name, call_id="c1", **args):
    return ToolCall(id=call_id, name=name, args=args)


def test_a_desktop_tool_always_needs_the_client():
    executor = Executor(TOOLS, DenyGate())

    assert executor.needs_client(call("ReadFile", file_path="a.txt")) is True
    assert executor.requires_approval(call("ReadFile", file_path="a.txt")) is False


def test_a_plain_server_tool_does_not_need_the_client():
    assert Executor(TOOLS, DenyGate()).needs_client(call("ListProjects")) is False


async def test_the_suspension_says_where_each_call_runs():
    executor = Executor(TOOLS, SuspendGate())

    with pytest.raises(ClientActionRequired) as exc:
        await executor.execute(
            [call("ReadFile", "a", file_path="x"), call("DeleteFile", "b", file_path="y")]
        )

    by_id = {request.call.id: request for request in exc.value.requests}
    assert by_id["a"].location is ToolLocation.DESKTOP
    assert by_id["a"].requires_approval is False
    assert by_id["b"].requires_approval is True


async def test_the_output_the_desktop_posted_becomes_the_result():
    executor = Executor(TOOLS, SuspendGate())

    results = await executor.execute(
        [call("ReadFile", file_path="a.txt")],
        {"c1": Decision(approved=True, output="hello from disk")},
    )

    assert results[0].content == "hello from disk"
    assert results[0].failed is False


async def test_a_failure_the_desktop_reports_stays_a_failure():
    executor = Executor(TOOLS, SuspendGate())

    results = await executor.execute(
        [call("ReadFile", file_path="a.txt")],
        {"c1": Decision(approved=True, output="FileNotFoundError: a.txt", failed=True)},
    )

    assert results[0].failed is True


async def test_a_refused_desktop_call_tells_the_model_not_to_retry():
    executor = Executor(TOOLS, SuspendGate())

    results = await executor.execute(
        [call("DeleteFile", file_path="a.txt")],
        {"c1": Decision(approved=False, feedback="archive it instead")},
    )

    assert "archive it instead" in results[0].content


async def test_with_no_desktop_connected_a_desktop_call_is_reported_not_run():
    executor = Executor(TOOLS, AutoApproveGate())

    results = await executor.execute([call("ReadFile", file_path="a.txt")])

    assert results[0].content == NO_DESKTOP.format(name="ReadFile")
    assert results[0].failed is True


async def test_an_oversized_result_is_truncated():
    async def huge() -> str:
        return "x" * 500

    executor = Executor(
        {"ListProjects": Tool(schema=ListProjects, handler=huge)},
        DenyGate(),
        max_output_chars=100,
    )

    results = await executor.execute([call("ListProjects")])

    assert results[0].content.startswith("x" * 100)
    assert "truncated" in results[0].content


async def test_the_loop_pauses_on_a_desktop_call_and_keeps_its_metadata():
    llm = FakeLLM(make_completion("", (call("ReadFile", file_path="a.txt"),)))

    result = await advance(
        LoopState(messages=[llm_domain.user("read a.txt")]), llm, Executor(TOOLS, SuspendGate())
    )

    assert result.status is LoopStatus.AWAITING_CLIENT
    assert result.state.pending_requests[0].location is ToolLocation.DESKTOP


async def test_the_loop_resumes_with_the_desktop_output():
    llm = FakeLLM(make_completion("", (call("ReadFile", file_path="a.txt"),)), "It says hello.")
    executor = Executor(TOOLS, SuspendGate())
    paused = await advance(LoopState(messages=[llm_domain.user("read a.txt")]), llm, executor)

    finished = await advance(
        paused.state, llm, executor, decisions={"c1": Decision(approved=True, output="hello")}
    )

    assert finished.status is LoopStatus.COMPLETED
    assert finished.state.pending_requests == ()
    assert {"role": "tool", "content": "hello", "tool_call_id": "c1"} in finished.state.messages


async def test_a_sub_assistant_that_finishes_reports_its_text():
    run = await run_assistant(
        FakeLLM("all done"), Executor(TOOLS, AutoApproveGate()), [llm_domain.user("go")]
    )

    assert run.finished is True
    assert run.text == "all done"


async def test_a_sub_assistant_out_of_steps_gives_its_own_account():
    looping = [make_completion("", (call("ListProjects", f"c{i}"),)) for i in range(2)]
    llm = FakeLLM(*looping, "I listed projects twice and wrote nothing.")

    run = await run_assistant(
        llm, Executor(TOOLS, AutoApproveGate()), [llm_domain.user("go")], max_iterations=2
    )

    assert run.finished is False
    assert run.text == "I listed projects twice and wrote nothing."
