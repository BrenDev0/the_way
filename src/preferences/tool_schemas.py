from pydantic import BaseModel, Field


class RememberPreference(BaseModel):
    """Save a standing preference the user has stated, so it applies on every future turn.

    Use this ONLY for a durable rule about how the user wants things done -- "always
    deliver reports to the Reports project", "answer me in Spanish", "never expose password
    hashes in a response schema". The user is asked to confirm before anything is saved,
    so proposing one costs them a click; proposing one for something they said once in
    passing wastes it.

    NOT for: facts about a task you are doing right now, anything you inferred rather than
    heard, or a multi-step procedure -- that is a skill. A preference is one sentence that
    would still be true next month.

    Already-saved preferences are shown to you every turn. Never re-save one of those."""

    preference: str = Field(
        description="The rule, as one short imperative sentence, for example 'Deliver "
        "finished reports to the Reports project unless told otherwise'"
    )
