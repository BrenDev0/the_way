import io
import zipfile

import pytest

from src.core.exceptions import ValidationError
from src.desktop import extract

SHEET_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def workbook(sheets: dict[str, str], shared: list[str] | None = None) -> bytes:
    """A minimal .xlsx: a zip of XML parts, as Excel writes it."""
    rels = "".join(
        f'<Relationship Id="rId{index}" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    listed = "".join(
        f'<sheet name="{name}" sheetId="{index}" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId{index}"/>'
        for index, name in enumerate(sheets, start=1)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/workbook.xml", f"<workbook {SHEET_NS}><sheets>{listed}</sheets></workbook>")
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
        )
        if shared is not None:
            strings = "".join(f"<si><t>{text}</t></si>" for text in shared)
            book.writestr("xl/sharedStrings.xml", f"<sst {SHEET_NS}>{strings}</sst>")
        for index, rows in enumerate(sheets.values(), start=1):
            book.writestr(f"xl/worksheets/sheet{index}.xml", f"<worksheet {SHEET_NS}><sheetData>{rows}</sheetData></worksheet>")
    return buffer.getvalue()


def test_an_excel_file_reads_as_its_sheets_with_cells_in_their_columns():
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2"><v>1500.5</v></c><c r="B2" t="b"><v>1</v></c>'
        '<c r="C2" t="inlineStr"><is><t>directo</t></is></c></row>'
        '<row r="3"></row>'
    )
    data = workbook({"Ventas": rows, "Notas": '<row r="1"><c r="A1" t="s"><v>2</v></c></row>'}, ["Cliente", "Total", "Hola"])

    assert extract.text_of(data, "ventas.xlsx") == "\n".join(
        ["## Ventas", "Cliente\t\tTotal", "1500.5\tTRUE\tdirecto", "", "## Notas", "Hola"]
    )


def test_a_workbook_with_no_shared_strings_still_reads():
    data = workbook({"Hoja1": '<row r="1"><c r="B1"><v>7</v></c></row>'})

    assert extract.text_of(data, "a.xlsx") == "## Hoja1\n\t7"


def test_a_file_of_another_kind_is_refused_with_its_own_code():
    with pytest.raises(ValidationError) as caught:
        extract.text_of(b"x", "foto.png")

    assert caught.value.code == "document_unsupported"


@pytest.mark.parametrize("name", ["roto.pdf", "roto.docx", "roto.xlsx"])
def test_a_damaged_file_is_said_to_be_unreadable_not_a_crash(name):
    with pytest.raises(ValidationError) as caught:
        extract.text_of(b"this is not that kind of file", name)

    assert caught.value.code == "document_unreadable"


def test_a_word_file_reads_its_paragraphs_and_tables():
    from docx import Document

    document = Document()
    document.add_paragraph("Contrato de servicios")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Cliente"
    table.rows[0].cells[1].text = "Acme"
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract.text_of(buffer.getvalue(), "contrato.docx")

    assert "Contrato de servicios" in text
    assert "Cliente\tAcme" in text
