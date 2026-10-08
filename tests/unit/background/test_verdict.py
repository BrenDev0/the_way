import pytest

from src.background.use_cases import reports_incomplete


@pytest.mark.parametrize(
    "report",
    [
        "RESULT: INCOMPLETE -- EditImage would not accept the source\nCreated notes.md",
        "\n  **RESULT: incomplete** — no image was made",
        "result:incomplete",
    ],
)
def test_a_worker_that_says_it_did_not_finish_is_incomplete(report):
    assert reports_incomplete(report)


@pytest.mark.parametrize(
    "report",
    [
        "RESULT: COMPLETE\nCreated capibara.png",
        # no verdict line: taken as complete, as before
        "Created capibara.png",
        # the word further down is not the verdict
        "RESULT: COMPLETE\nThe earlier draft was incomplete, so I redid it.",
    ],
)
def test_anything_else_is_complete(report):
    assert not reports_incomplete(report)
