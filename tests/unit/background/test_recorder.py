from src.background.jobs import MAX_RECORDED_ARG_CHARS, CallRecorder
from src.core.llm.domain import ToolCall


async def test_each_call_is_kept_with_its_arguments_clipped():
    recorder = CallRecorder(None)

    await recorder.tool_started(ToolCall(id="1", name="ReadSkill", args={"name": "landing-pages"}))
    await recorder.tool_started(
        ToolCall(id="2", name="WriteProjectFile", args={"path": "a.html", "content": "x" * 50_000})
    )

    assert [call["name"] for call in recorder.calls] == ["ReadSkill", "WriteProjectFile"]
    assert recorder.calls[0]["args"] == {"name": "landing-pages"}
    assert len(recorder.calls[1]["args"]["content"]) == MAX_RECORDED_ARG_CHARS


async def test_the_events_still_reach_the_conversation():
    seen = []

    class Events:
        async def tool_started(self, call):
            seen.append(("started", call.name))

        async def tool_finished(self, call, result):
            seen.append(("finished", call.name))

    recorder = CallRecorder(Events())
    call = ToolCall(id="1", name="ListProjects", args={})
    await recorder.tool_started(call)
    await recorder.tool_finished(call, None)

    assert seen == [("started", "ListProjects"), ("finished", "ListProjects")]
