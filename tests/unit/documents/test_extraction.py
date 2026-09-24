import pytest

from src.documents import extraction
from src.documents.config import MAX_EXTRACTED_CHARS


@pytest.fixture
def written(tmp_path):
    def write(name: str, content: bytes):
        path = tmp_path / name
        path.write_bytes(content)
        return path

    return write


def test_markdown_is_read_as_text(written):
    source = written("policy.md", b"# Policy\n\nBe kind.")

    assert extraction.extract(source, "policy.md") == "# Policy\n\nBe kind."


def test_windows_line_endings_are_normalised(written):
    source = written("notes.txt", b"one\r\ntwo\r\n")

    assert extraction.extract(source, "notes.txt") == "one\ntwo"


def test_trailing_whitespace_is_stripped_per_line(written):
    source = written("notes.txt", b"one   \ntwo\t\n")

    assert extraction.extract(source, "notes.txt") == "one\ntwo"


def test_runs_of_blank_lines_are_collapsed(written):
    source = written("notes.txt", b"one\n\n\n\n\ntwo")

    assert extraction.extract(source, "notes.txt") == "one\n\ntwo"


def test_latin1_content_does_not_explode(written):
    source = written("notes.txt", "caf\xe9".encode("latin-1"))

    assert "caf" in extraction.extract(source, "notes.txt")


def test_an_unknown_extension_is_unsupported(written):
    source = written("logo.png", b"\x89PNG\r\n\x1a\n")

    with pytest.raises(extraction.UnsupportedDocument):
        extraction.extract(source, "logo.png")


def test_a_file_with_no_extension_is_unsupported(written):
    source = written("README", b"hello")

    with pytest.raises(extraction.UnsupportedDocument):
        extraction.extract(source, "README")


def test_the_extension_is_read_from_the_declared_filename(written):
    source = written("blob", b"hello there")

    assert extraction.extract(source, "notes.txt") == "hello there"


def test_a_windows_path_still_yields_its_suffix():
    assert extraction.suffix_of("C:\\docs\\brand.PDF") == ".pdf"


def test_extraction_is_capped(written):
    source = written("big.txt", b"x" * (MAX_EXTRACTED_CHARS + 5000))

    assert len(extraction.extract(source, "big.txt")) == MAX_EXTRACTED_CHARS


def test_a_real_pdf_round_trips(tmp_path):
    pypdf = pytest.importorskip("pypdf")

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    source = tmp_path / "blank.pdf"
    with source.open("wb") as handle:
        writer.write(handle)

    assert extraction.extract(source, "blank.pdf") == ""


def test_a_real_word_document_round_trips(tmp_path):
    docx = pytest.importorskip("docx")

    document = docx.Document()
    document.add_paragraph("Brand voice")
    document.add_paragraph("Warm, plain, never breathless.")
    source = tmp_path / "brand.docx"
    document.save(str(source))

    extracted = extraction.extract(source, "brand.docx")

    assert "Brand voice" in extracted
    assert "never breathless" in extracted
