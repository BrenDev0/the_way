from datetime import UTC, datetime
from uuid import uuid4

from src.skills import usage

MONDAY = datetime(2026, 10, 12, tzinfo=UTC)
TUESDAY = datetime(2026, 10, 13, tzinfo=UTC)


def call(tool, **args):
    return {"id": str(uuid4()), "name": tool, "args": args, "type": "tool_call"}


def test_reads_and_hand_ons_are_counted_per_skill():
    first, second = uuid4(), uuid4()
    skills, reading, unknown = usage.tally(
        ["landing-pages", "business-case", "meeting-minutes"],
        [
            (first, MONDAY, [call("ReadSkill", name="landing-pages"), call("ListProjects")]),
            (first, MONDAY, [call("BuildHtmlPage", brief="...", skill="landing-pages")]),
            (second, TUESDAY, [call("StartBackgroundTask", instructions="...", skills=["landing-pages", "business-case"])]),
            (second, TUESDAY, [call("ReadSkill", name="no-such-skill")]),
        ],
    )

    assert skills["landing-pages"].reads == 1
    assert skills["landing-pages"].handed_on == 2
    assert skills["landing-pages"].conversations == {first, second}
    assert skills["landing-pages"].last == TUESDAY
    assert skills["business-case"].reads == 0
    assert skills["business-case"].handed_on == 1
    assert skills["meeting-minutes"].last is None
    # only a ReadSkill counts a conversation as reading skills
    assert reading == {first}
    assert unknown == {"no-such-skill": 1}


def test_the_report_names_the_skills_never_used():
    skills, _reading, _unknown = usage.tally(["landing-pages", "business-case"], [])
    text = usage.render(
        usage.Usage(
            since=MONDAY, skills=skills, conversations=4, conversations_reading=0,
            tasks=2, tasks_with_skills=0,
        )
    )

    assert "that read at least one skill: 0/4 (0%)" in text
    assert "Never used in this window: 2 of 2 skills." in text
