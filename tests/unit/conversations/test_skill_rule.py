"""A skill is the customer's: the system knows no skill by name, and says one thing about all of them."""

import pytest

from src.background import prompt as background_prompt
from src.conversations import prompt

# Skills of a sample kit a customer might upload. The system must not know any of them.
SAMPLE_KIT = (
    "output-documents",
    "landing-pages",
    "drift-check",
    "session-handoff",
    "delivery-routing",
    "capture-system",
    "signal-extraction",
    "using-this-kit",
    "ai-ops-measurement",
    "content-reverse-engineering",
)


@pytest.mark.parametrize("text", [prompt.SYSTEM, background_prompt.SYSTEM_PROMPT], ids=["agent", "background-worker"])
def test_no_prompt_names_a_skill_a_customer_might_have_uploaded(text):
    assert [name for name in SAMPLE_KIT if name in text] == []


def test_the_agent_is_told_how_to_treat_any_skill_written_for_another_agent():
    rule = prompt.SYSTEM

    assert "WRITTEN BY PEOPLE, OFTEN FOR OTHER AGENTS" in rule
    assert "Follow its method, not its tool names" in rule
    assert "RunCommand" in rule and "desktop app only" in rule
    assert "the user approves each one" in rule
    assert "Never claim to have done a step you did not do" in rule


def test_a_background_worker_is_told_the_same_without_a_shell():
    text = background_prompt.SYSTEM_PROMPT

    assert "wrote it for another agent" in text
    assert "do not invent it" in text
    assert "RunCommand" not in text  # a worker never has it
