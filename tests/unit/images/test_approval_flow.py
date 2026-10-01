"""A call that always asks: the approver's model pick, and a background run that stops on
it, is saved, and carries on days later from exactly where it stopped."""

import json
from uuid import uuid4

import pytest
from helpers import FakeCacheStore, FakeLLM, make_completion
from pydantic import BaseModel

from src.background import paused
from src.core.agents.domain import LoopState
from src.core.agents.runner import AssistantRun, Suspended, continue_assistant
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import (
    ClientActionRequired,
    ClientRequest,
    Decision,
    Tool,
    chosen_args,
)
from src.core.tools.executor import Executor
from src.core.tools.gates import AskOnlyGate
from src.images import config as images_config


class Draw(BaseModel):
    """Draw a picture."""

    prompt: str
    model: str = images_config.FLARE


class Note(BaseModel):
    """Write a note."""

    text: str


def tools(drawn: list[dict]) -> dict[str, Tool]:
    async def draw(prompt: str, model: str = images_config.FLARE) -> str:
        drawn.append({"prompt": prompt, "model": model})
        return f"drew {prompt} with {model}"

    async def note(text: str) -> str:
        return f"noted {text}"

    return {
        "Draw": Tool(
            schema=Draw, handler=draw, requires_approval=True, always_ask=True,
            choices={"model": images_config.MODELS},
        ),
        # needs approval too, but nothing the worker cannot approve itself
        "Note": Tool(schema=Note, handler=note, requires_approval=True),
    }


def test_an_approver_can_pick_only_what_the_tool_offers():
    tool = tools([])["Draw"]
    call = ToolCall(id="c1", name="Draw", args={"prompt": "a cat", "model": images_config.FLARE})

    picked = chosen_args(tool, call, Decision(approved=True, args={"model": images_config.SUNBURST}))
    smuggled = chosen_args(tool, call, Decision(approved=True, args={"model": "gpt-4o", "prompt": "x"}))

    assert picked["model"] == images_config.SUNBURST
    assert smuggled == call.args


async def test_the_worker_approves_its_own_calls_but_stops_on_one_that_must_ask():
    gate = AskOnlyGate(frozenset({"Draw"}))
    note = ClientRequest(call=ToolCall(id="n", name="Note", args={}), requires_approval=True)
    draw = ClientRequest(call=ToolCall(id="d", name="Draw", args={}), requires_approval=True)

    assert (await gate.decide([note]))[0].approved
    with pytest.raises(ClientActionRequired) as stopped:
        await gate.decide([note, draw])
    assert [r.call.id for r in stopped.value.requests] == ["d"]


async def test_a_run_stops_for_approval_is_saved_and_resumes_with_the_model_picked():
    drawn: list[dict] = []
    registry = tools(drawn)
    llm = FakeLLM(
        make_completion(
            "",
            (
                ToolCall(id="d1", name="Draw", args={"prompt": "three banners"}),
                ToolCall(id="n1", name="Note", args={"text": "brief"}),
            ),
        ),
        make_completion("Done: banners drawn."),
    )
    executor = Executor(registry, AskOnlyGate(frozenset({"Draw"})))
    start = LoopState(messages=[llm_domain.system("work"), llm_domain.user("make banners")])

    stopped = await continue_assistant(llm, executor, start)

    assert isinstance(stopped, Suspended)
    assert drawn == []  # nothing is spent before the user says so
    assert [r.call.id for r in stopped.state.pending_requests] == ["d1"]

    # saved, as it would sit in Redis for days -- through real JSON
    cache = FakeCacheStore()
    task_id = uuid4()
    await paused.save(cache, task_id, paused.PausedRun(stopped.state))
    cache.data = json.loads(json.dumps(cache.data))
    assert cache.ttls[f"background:paused:{task_id}"] == 7 * 24 * 60 * 60

    waiting = await paused.load(cache, task_id)
    assert waiting is not None
    answered = paused.answered(
        waiting, {"d1": Decision(approved=True, args={"model": images_config.SUNBURST})}
    )

    resumed = await continue_assistant(llm, executor, answered.state, decisions=answered.decisions)

    assert isinstance(resumed, AssistantRun) and resumed.finished
    assert resumed.text == "Done: banners drawn."
    assert drawn == [{"prompt": "three banners", "model": images_config.SUNBURST}]


async def test_one_approval_carries_a_run_through_ten_images_with_the_model_picked():
    from src.background.jobs import _allowance
    from src.core.tools.gates import AllowanceGate
    from src.images import config as images_config

    def cost(request: ClientRequest) -> int:
        return 3 if request.call.name == "Draw" else 0

    # the user approved a 3-image call and picked Sunburst
    first = ToolCall(id="d1", name="GenerateImages", args={"images": [{}, {}, {}], "model": images_config.FLARE})
    resumed = paused.PausedRun(
        LoopState(pending_requests=(ClientRequest(call=first, requires_approval=True),)),
        {"d1": Decision(approved=True, args={"model": images_config.SUNBURST})},
    )
    allowance = _allowance(resumed)
    assert allowance is not None and allowance.remaining == 7 and allowance.args == {"model": images_config.SUNBURST}

    gate = AllowanceGate(frozenset({"Draw"}), allowance, cost)
    draw = ClientRequest(call=ToolCall(id="d2", name="Draw", args={}), requires_approval=True)
    for _ in range(2):  # 3 + 3 more go through on their own, with the model picked
        decision = (await gate.decide([draw]))[0]
        assert decision.approved and decision.args == {"model": images_config.SUNBURST}
    assert allowance.remaining == 1
    with pytest.raises(ClientActionRequired):  # the 10 are used up: ask again
        await gate.decide([draw])


def test_a_refusal_grants_nothing():
    from src.background.jobs import _allowance

    call = ToolCall(id="d1", name="EditImage", args={"output_paths": ["a.png"]})
    resumed = paused.PausedRun(
        LoopState(pending_requests=(ClientRequest(call=call, requires_approval=True),)),
        {"d1": Decision(approved=False)},
    )
    assert _allowance(resumed) is None


async def test_a_refused_image_is_skipped_and_the_run_carries_on():
    drawn: list[dict] = []
    llm = FakeLLM(
        make_completion("", (ToolCall(id="d1", name="Draw", args={"prompt": "x"}),)),
        make_completion("Finished without the image."),
    )
    executor = Executor(tools(drawn), AskOnlyGate(frozenset({"Draw"})))

    stopped = await continue_assistant(llm, executor, LoopState(messages=[llm_domain.user("go")]))
    assert isinstance(stopped, Suspended)
    resumed = await continue_assistant(
        llm, executor, stopped.state, decisions={"d1": Decision(approved=False, feedback="no images")}
    )

    assert isinstance(resumed, AssistantRun) and resumed.text == "Finished without the image."
    assert drawn == []
