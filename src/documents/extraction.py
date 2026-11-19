import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .config import MAX_EXTRACTED_CHARS

TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

TEXT_SUFFIXES = frozenset(
    {
        ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl",
        ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".sql",
        ".ini", ".cfg", ".toml", ".log",
    }
)

PDF_SUFFIXES = frozenset({".pdf"})
WORD_SUFFIXES = frozenset({".docx"})
EXCEL_SUFFIXES = frozenset({".xlsx"})

MAX_SPREADSHEET_XML_BYTES = 200 * 1024 * 1024

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_OFFICE_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class UnsupportedDocument(Exception):
    pass


def suffix_of(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def extract(source: Path, filename: str) -> str:
    suffix = suffix_of(filename)

    if suffix in PDF_SUFFIXES:
        text = _from_pdf(source)
    elif suffix in WORD_SUFFIXES:
        text = _from_word(source)
    elif suffix in EXCEL_SUFFIXES:
        text = _from_excel(source)
    elif suffix in TEXT_SUFFIXES:
        text = _from_text(source)
    else:
        raise UnsupportedDocument(f"No extractor for '{suffix or filename}'")

    return _tidy(text)[:MAX_EXTRACTED_CHARS]


def _from_pdf(source: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(source))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _from_word(source: Path) -> str:
    from docx import Document as WordDocument

    document = WordDocument(str(source))
    blocks = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.append("\t".join(cell.text for cell in row.cells))

    return "\n".join(blocks)


def _from_excel(source: Path) -> str:
    with zipfile.ZipFile(source) as book:
        if sum(info.file_size for info in book.infolist()) > MAX_SPREADSHEET_XML_BYTES:
            raise ValueError("The spreadsheet is too large to read")

        shared = _shared_strings(book)
        targets = _sheet_targets(book)
        blocks = []
        for name, target in targets:
            rows = _sheet_rows(ElementTree.fromstring(book.read(target)), shared)
            blocks.append(f"## {name}\n" + "\n".join(rows))

    return "\n\n".join(blocks)


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{_MAIN}t")) for item in root.iter(f"{_MAIN}si")]


def _sheet_targets(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    paths = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{_RELS}Relationship")}
    found = []
    for sheet in workbook.iter(f"{_MAIN}sheet"):
        target = paths.get(sheet.get(_OFFICE_REL), "")
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        if path in book.namelist():
            found.append((sheet.get("name", "Sheet"), path))
    return found


def _sheet_rows(sheet: ElementTree.Element, shared: list[str]) -> list[str]:
    rows = []
    for row in sheet.iter(f"{_MAIN}row"):
        cells: dict[int, str] = {}
        for cell in row.iter(f"{_MAIN}c"):
            value = _cell_value(cell, shared)
            if value:
                cells[_column(cell.get("r", ""))] = value
        if cells:
            rows.append("\t".join(cells.get(index, "") for index in range(max(cells) + 1)))
    return rows


def _cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_MAIN}t"))
    raw = cell.findtext(f"{_MAIN}v") or ""
    if kind == "s":
        return shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw.replace("\t", " ").replace("\n", " ")


def _column(reference: str) -> int:
    letters = re.match(r"[A-Za-z]+", reference)
    index = 0
    for letter in (letters.group(0).upper() if letters else "A"):
        index = index * 26 + ord(letter) - 64
    return index - 1


def _from_text(source: Path) -> str:
    raw = source.read_bytes()

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")

    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace")


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]

    tidied: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            tidied.append(line)
            continue
        blanks += 1
        if blanks < 2:
            tidied.append("")

    return "\n".join(tidied).strip()
