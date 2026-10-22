"""The agent's name is AGENTIX, and every prompt that speaks as the assistant says so, so it
answers to it and uses it. The front ends show the same name wherever they say the agent is
working (searching the apps for AGENTIX finds each place)."""

import pytest

from src.background import prompt as background_prompt
from src.conversations import prompt as conversation_prompt
from src.skills import prompt as skills_prompt

NAME = "AGENTIX"


@pytest.mark.parametrize(
    "prompt",
    [conversation_prompt.SYSTEM, background_prompt.SYSTEM_PROMPT, skills_prompt.BUILDER_PROMPT],
    ids=["conversation", "background worker", "skill author"],
)
def test_every_prompt_that_speaks_as_the_assistant_names_it(prompt):
    # in the opening sentence, where a model takes its identity from
    assert NAME in prompt.splitlines()[0]


def test_the_main_assistant_is_told_to_answer_to_the_name_and_use_it():
    opening = conversation_prompt.SYSTEM[:400]

    assert "Your name is AGENTIX" in opening
    assert "who you are or what you are called" in opening
