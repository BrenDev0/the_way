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


def test_an_extracted_document_is_offered_without_training():
    # Waiting on someone to press "Entrenar" left uploaded brand books invisible.
    block = context.render([], [make_document(title="Brand Book", status=DocumentStatus.EXTRACTED)])

    assert "Brand Book" in block


def test_a_failed_document_is_not_offered():
    assert context.render([], [make_document(status=DocumentStatus.FAILED)]) == ""


def test_a_document_says_which_brand_it_is_about():
    document = make_document(title="Manual de marca")
    document.brand = "Soullens"

    assert "Manual de marca (brand: Soullens):" in context.render([], [document])


def test_the_library_is_listed_by_brand_folder():
    block = context.render([], [], ("Biblioteca", ["ClienteX/logo.svg", "Soullens/logo.png", "Soullens/paleta.png", "general.png"]))

    assert "project:Biblioteca/ClienteX/logo.svg" in block  # the example uses a real file
    assert "- ClienteX/: logo.svg" in block
    assert "- Soullens/: logo.png, paleta.png" in block
    assert block.index("Soullens/") < block.index("(top level, not a brand): general.png")
    assert "never another client's logo" in block


def test_an_empty_library_adds_nothing():
    assert context.render([], [], ("Biblioteca", [])) == ""


def test_a_full_brand_folder_says_where_to_see_the_rest():
    files = [f"Soullens/img-{index:02}.png" for index in range(config.MAX_LIBRARY_FILES_PER_BRAND + 5)]

    block = context.render([], [], ("Biblioteca", files))

    assert "(+5 more: ListProjectFolder 'Biblioteca' 'Soullens')" in block


def test_a_long_document_is_read_in_sections_that_say_where_the_next_starts():
    from src.knowledge.tools import section

    text = "a" * 15_000 + "\n\n" + "b" * 15_000

    first = section(text, 0)
    assert first.startswith("[Characters 0-15,002 of 30,002. Continue with offset=15002.]")
    assert "b" not in first.split("\n\n", 1)[1]  # cut at the paragraph break
    assert section(text, 15_002).startswith("[Characters 15,002-30,002 of 30,002. This is the end.]")
    assert section(text, 40_000).startswith("[End of document")
    assert section("short", 0) == "short"
