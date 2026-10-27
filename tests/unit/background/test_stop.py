"""What a stopped background task says, and what is kept so it can carry on."""

from uuid import uuid4

from helpers import FakeCacheStore

from src.background import paused
from src.background import use_cases as background_use_cases
from src.core.agents.domain import LoopState
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall


def test_a_stopped_result_says_who_stopped_it_what_was_made_and_how_to_carry_on():
    text = background_use_cases.stopped_result("Files in .the_way/tasks/x: part1.md.")

    assert text.startswith(background_use_cases.STOPPED_MARKER)
    assert "part1.md" in text
    assert "nothing was delivered" in text
    assert "ResumeBackgroundTask" in text
    assert "do not start it again from scratch" in text


def test_a_task_that_could_not_keep_its_place_says_it_cannot_be_resumed():
    text = background_use_cases.stopped_result("", resumable=False)

    assert "cannot be resumed" in text
    assert "ResumeBackgroundTask" not in text


def test_a_stopped_task_is_not_mistaken_for_a_failed_one():
    stopped = background_use_cases.stopped_result("")

    assert not stopped.startswith(background_use_cases.FAILURE_MARKER)


async def test_a_kept_run_remembers_it_was_stopped_and_what_it_had_done():
    cache = FakeCacheStore()
    task_id = uuid4()
    state = LoopState(
        messages=[llm_domain.user("task"), llm_domain.assistant("", (ToolCall(id="c1", name="X", args={}),))],
        iterations_used=4,
    )

    await paused.save(cache, task_id, paused.PausedRun(state, stopped=True))
    loaded = await paused.load(cache, task_id)

    assert loaded.stopped is True
    assert loaded.state.iterations_used == 4
    assert len(loaded.state.messages) == 2


async def test_a_run_suspended_for_an_approval_is_not_marked_stopped():
    cache = FakeCacheStore()
    task_id = uuid4()

    await paused.save(cache, task_id, paused.PausedRun(LoopState(messages=[llm_domain.user("task")])))

    assert (await paused.load(cache, task_id)).stopped is False


async def test_a_run_saved_before_stopping_existed_still_loads():
    cache = FakeCacheStore()
    task_id = uuid4()
    await paused.save(cache, task_id, paused.PausedRun(LoopState(messages=[llm_domain.user("task")])))
    cache.data[f"background:paused:{task_id}"].pop("stopped")

    assert (await paused.load(cache, task_id)).stopped is False
