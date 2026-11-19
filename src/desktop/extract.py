import tempfile
from pathlib import Path

from src.core.exceptions import ValidationError
from src.documents import extraction


def text_of(data: bytes, name: str) -> str:
    suffix = extraction.suffix_of(name)
    if suffix not in extraction.PDF_SUFFIXES | extraction.WORD_SUFFIXES | extraction.EXCEL_SUFFIXES:
        raise ValidationError(
            message=f"Text cannot be read from '{suffix or name}' files", code="document_unsupported"
        )

    with tempfile.TemporaryDirectory() as workspace:
        source = Path(workspace) / f"file{suffix}"
        source.write_bytes(data)
        try:
            return extraction.extract(source, name)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(
                message=f"'{name}' could not be read: it may be damaged or protected with a password",
                code="document_unreadable",
            ) from exc
