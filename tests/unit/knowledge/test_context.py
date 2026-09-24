from helpers import make_document, make_skill

from src.documents.domain import DocumentStatus
from src.knowledge import config, context


def test_nothing_renders_when_there_is_nothing_to_offer():
    assert context.render([], []) == ""


def test_a_skill_is_listed_by_name_and_description():
    block = context.render([make_skill(name="brand-voice", description="Company voice.")], [])

    assert "- brand-voice: Company voice." in block


def test_a_document_is_listed_with_its_id_in_brackets():
    document = make_document(title="Brand Book", description="Identity.")

    block = context.render([], [document])

    assert f"- [{document.id}] Brand Book: Identity." in block


def test_the_tool_names_are_named_so_the_model_can_call_them():
    block = context.render([make_skill()], [make_document()])

    assert "ReadSkill" in block
    assert "ReadKnowledgeDocument" in block


def test_a_document_that_is_not_ready_is_not_offered():
    block = context.render([], [make_document(status=DocumentStatus.EXTRACTING)])

    assert block == ""


def test_an_unsupported_document_is_not_offered():
    block = context.render([], [make_document(status=DocumentStatus.UNSUPPORTED)])

    assert block == ""


def test_a_trained_document_is_offered_alongside_an_untrained_one():
    ready = make_document(title="Trained", status=DocumentStatus.TRAINED)
    pending = make_document(title="Pending", status=DocumentStatus.PENDING)

    block = context.render([], [ready, pending])

    assert "Trained" in block
    assert "Pending" not in block


def test_a_missing_description_says_so_rather_than_trailing_off():
    block = context.render([make_skill(description="")], [])

    assert "(no description)" in block


def test_a_long_description_is_clipped():
    block = context.render([make_skill(description="x" * 500)], [])

    longest = max(len(line) for line in block.splitlines())
    assert longest < config.MAX_DESCRIPTION_CHARS + 60


def test_a_multiline_description_is_flattened():
    block = context.render([make_skill(description="one\n\ntwo")], [])

    assert "- brand-voice: one two" in block


def test_the_skill_listing_is_capped():
    skills = [make_skill(name=f"skill-{index}") for index in range(config.MAX_INDEX_ENTRIES + 15)]

    block = context.render(skills, [])

    listed = [line for line in block.splitlines() if line.startswith("- skill-")]
    assert len(listed) == config.MAX_INDEX_ENTRIES


def test_the_overflow_is_reported_rather_than_hidden():
    skills = [make_skill(name=f"skill-{index}") for index in range(config.MAX_INDEX_ENTRIES + 15)]

    block = context.render(skills, [])

    assert "and 15 more skills" in block


def test_the_document_listing_is_capped():
    documents = [
        make_document(title=f"Doc {index}")
        for index in range(config.MAX_INDEX_ENTRIES + 3)
    ]

    block = context.render([], documents)

    listed = [line for line in block.splitlines() if line.startswith("- [")]
    assert len(listed) == config.MAX_INDEX_ENTRIES
    assert "and 3 more documents" in block


def test_the_whole_block_stays_small_enough_to_resend_every_turn():
    skills = [
        make_skill(name=f"skill-{index}", description="x" * 400)
        for index in range(200)
    ]
    documents = [make_document(description="y" * 400) for _ in range(200)]

    block = context.render(skills, documents)

    assert len(block) < 40_000


def test_an_untrained_document_is_not_offered_to_the_agent():
    block = context.render([], [make_document(status=DocumentStatus.EXTRACTED)])

    assert block == ""


def test_training_is_what_makes_a_document_visible():
    document = make_document(title="Brand Book", status=DocumentStatus.EXTRACTED)

    assert context.render([], [document]) == ""

    document.status = DocumentStatus.TRAINED

    assert "Brand Book" in context.render([], [document])
