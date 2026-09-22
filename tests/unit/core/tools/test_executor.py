import asyncio

import pytest
from pydantic import BaseModel

from src.core.llm.domain import ToolCall
from src.core.tools.domain import (
    ApprovalRequest,
    ApprovalRequired,
    Decision,
    Tool,
    ToolResult,
)
from src.core.tools.executor import Executor
from src.core.tools.gates import AutoApproveGate, DenyGate


class ReadFile(BaseModel):
    path: str


class DeleteFile(BaseModel):
    path: str


class SlowTool(BaseModel):
    seconds: float


async def read_file(path: str) -> str:
    return f"contents of {path}"


def delete_file(path: str) -> str:
    return f"deleted {path}"


async def explodes(path: str) -> str:
    raise RuntimeError("disk on fire")


class RecordingGate:
    def __init__(self, decisions=None):
        self.seen: list[ApprovalRequest] = []
        self._decisions = decisions

    async def decide(self, requests):
        self.seen.extend(requests)
        if self._decisions is None:
            return tuple(Decision(approved=True) for _ in requests)
        return self._decisions


class SuspendingGate:
    async def decide(self, requests):
        raise ApprovalRequired(tuple(requests))


class RecordingEvents:
    def __init__(self):
        self.started: list[str] = []
        self.finished: list[str] = []

    async def tool_started(self, call):
        self.started.append(call.name)

    async def tool_finished(self, call, result):
        self.finished.append(call.name)


def tools(**overrides):
    base = {
        "ReadFile": Tool(schema=ReadFile, handler=read_file),
        "DeleteFile": Tool(schema=DeleteFile, handler=delete_file, requires_approval=True),
    }
    base.update(overrides)
    return base


def call(name, call_id="c1", **args):
    return ToolCall(id=call_id, name=name, args=args)


def executor(gate=None, **overrides):
    return Executor(tools(**overrides), gate or DenyGate())


async def test_ungated_tool_runs_without_consulting_the_gate():
    gate = RecordingGate()

    results = await executor(gate).execute([call("ReadFile", path="x.txt")])

    assert results[0].content == "contents of x.txt"
    assert gate.seen == []


async def test_sync_handlers_run_in_a_thread():
    results = await executor(AutoApproveGate()).execute([call("DeleteFile", path="x.txt")])

    assert results[0].content == "deleted x.txt"


async def test_gated_tool_asks_the_gate():
    gate = RecordingGate()

    await executor(gate).execute([call("DeleteFile", path="x.txt")])

    assert [r.call.name for r in gate.seen] == ["DeleteFile"]


async def test_denial_returns_guidance_instead_of_running():
    gate = RecordingGate(decisions=(Decision(approved=False),))

    results = await executor(gate).execute([call("DeleteFile", path="x.txt")])

    assert "denied" in results[0].content
    assert "deleted x.txt" not in results[0].content


async def test_denial_with_feedback_relays_the_instruction():
    gate = RecordingGate(decisions=(Decision(approved=False, feedback="rename it instead"),))

    results = await executor(gate).execute([call("DeleteFile", path="x.txt")])

    assert "rename it instead" in results[0].content


async def test_supplied_decisions_skip_the_gate():
    gate = RecordingGate()
    approved = {"c1": Decision(approved=True)}

    results = await executor(gate).execute([call("DeleteFile", path="x.txt")], approved)

    assert results[0].content == "deleted x.txt"
    assert gate.seen == []


async def test_a_supplied_denial_is_honoured_on_resume():
    gate = RecordingGate()
    denied = {"c1": Decision(approved=False)}

    results = await executor(gate).execute([call("DeleteFile", path="x.txt")], denied)

    assert "denied" in results[0].content
    assert gate.seen == []


async def test_a_suspending_gate_stops_the_batch():
    with pytest.raises(ApprovalRequired) as exc:
        await executor(SuspendingGate()).execute([call("DeleteFile", path="x.txt")])

    assert [r.call.name for r in exc.value.requests] == ["DeleteFile"]


async def test_the_whole_gated_batch_is_offered_at_once():
    calls = [
        call("DeleteFile", "c1", path="a.txt"),
        call("DeleteFile", "c2", path="b.txt"),
    ]

    with pytest.raises(ApprovalRequired) as exc:
        await executor(SuspendingGate()).execute(calls)

    assert [r.call.id for r in exc.value.requests] == ["c1", "c2"]


async def test_results_keep_the_order_of_the_calls():
    calls = [
        call("ReadFile", "c1", path="a.txt"),
        call("ReadFile", "c2", path="b.txt"),
        call("ReadFile", "c3", path="c.txt"),
    ]

    results = await executor().execute(calls)

    assert [r.tool_call_id for r in results] == ["c1", "c2", "c3"]


async def test_calls_run_concurrently():
    async def sleeper(seconds: float) -> str:
        await asyncio.sleep(seconds)
        return "done"

    runner = Executor(
        {"SlowTool": Tool(schema=SlowTool, handler=sleeper)},
        DenyGate(),
    )
    calls = [call("SlowTool", f"c{i}", seconds=0.05) for i in range(5)]

    started = asyncio.get_running_loop().time()
    await runner.execute(calls)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.2


async def test_an_unknown_tool_is_reported_not_raised():
    results = await executor().execute([call("NoSuchTool", path="x")])

    assert results[0].failed
    assert "NoSuchTool" in results[0].content


async def test_a_failing_handler_becomes_a_result_the_model_can_read():
    results = await executor(
        AutoApproveGate(), Explodes=Tool(schema=ReadFile, handler=explodes)
    ).execute([call("Explodes", path="x.txt")])

    assert results[0].failed
    assert "disk on fire" in results[0].content


async def test_events_are_emitted_for_a_run_tool():
    events = RecordingEvents()
    runner = Executor(tools(), DenyGate(), events)

    await runner.execute([call("ReadFile", path="x.txt")])

    assert events.started == ["ReadFile"]
    assert events.finished == ["ReadFile"]


async def test_no_events_for_a_denied_tool():
    events = RecordingEvents()
    runner = Executor(tools(), RecordingGate(decisions=(Decision(approved=False),)), events)

    await runner.execute([call("DeleteFile", path="x.txt")])

    assert events.started == []


async def test_a_tool_outside_the_set_is_never_approved():
    assert executor().requires_approval(call("NoSuchTool")) is False


async def test_requires_approval_reflects_the_tool():
    runner = executor()

    assert runner.requires_approval(call("DeleteFile", path="x")) is True
    assert runner.requires_approval(call("ReadFile", path="x")) is False


async def test_previews_and_details_reach_the_gate():
    gate = RecordingGate()
    runner = Executor(
        tools(
            DeleteFile=Tool(
                schema=DeleteFile,
                handler=delete_file,
                requires_approval=True,
                preview=lambda path: f"would delete {path}",
                describe=lambda path: f"delete {path}",
            )
        ),
        gate,
    )

    await runner.execute([call("DeleteFile", path="x.txt")])

    assert gate.seen[0].preview == "would delete x.txt"
    assert gate.seen[0].detail == "delete x.txt"


async def test_a_broken_preview_does_not_block_the_call():
    def exploding_preview(**_):
        raise ValueError("cannot preview")

    gate = RecordingGate()
    runner = Executor(
        tools(
            DeleteFile=Tool(
                schema=DeleteFile,
                handler=delete_file,
                requires_approval=True,
                preview=exploding_preview,
            )
        ),
        gate,
    )

    results = await runner.execute([call("DeleteFile", path="x.txt")])

    assert gate.seen[0].preview is None
    assert results[0].content == "deleted x.txt"


def test_tool_name_comes_from_its_schema():
    assert Tool(schema=ReadFile, handler=read_file).name == "ReadFile"


async def test_deny_gate_denies_everything():
    decisions = await DenyGate().decide([ApprovalRequest(call=call("DeleteFile"))])

    assert decisions[0].approved is False


async def test_auto_approve_gate_approves_everything():
    decisions = await AutoApproveGate().decide([ApprovalRequest(call=call("DeleteFile"))])

    assert decisions[0].approved is True


async def test_default_gate_choice_is_the_callers_and_denial_is_safe():
    results = await Executor(tools(), DenyGate()).execute([call("DeleteFile", path="x.txt")])

    assert "denied" in results[0].content
    assert isinstance(results[0], ToolResult)
