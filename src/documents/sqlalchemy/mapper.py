from src.documents.domain import Document, DocumentCreate, DocumentStatus

from .models import DocumentRow


def row_to_domain(row: DocumentRow) -> Document:
    return Document(
        id=row.id,
        organization_id=row.organization_id,
        title=row.title,
        description=row.description,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        status=DocumentStatus(row.status),
        extracted_chars=row.extracted_chars,
        uploaded_by=row.uploaded_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(document: DocumentCreate) -> DocumentRow:
    return DocumentRow(
        organization_id=document.organization_id,
        title=document.title,
        description=document.description,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=DocumentStatus.PENDING,
        extracted_text=None,
        extracted_chars=0,
        uploaded_by=document.uploaded_by,
    )
