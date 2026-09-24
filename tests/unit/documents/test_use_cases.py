from uuid import uuid4

import pytest
from helpers import FakeBucketStore, make_document

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.documents import config, keys
from src.documents import use_cases as documents_use_cases
from src.documents.domain import DocumentStatus


@pytest.fixture
def organization_id():
    return uuid4()


@pytest.fixture
def bucket():
    return FakeBucketStore()


@pytest.fixture
def request_upload(organization_id, bucket):
    created = []

    async def run(count: int = 0, **overrides):
        async def count_documents_fn(_organization_id):
            return count

        async def create_document_fn(document):
            created.append(document)
            return make_document(
                organization_id=document.organization_id,
                title=document.title,
                description=document.description,
                filename=document.filename,
                content_type=document.content_type,
                size_bytes=document.size_bytes,
                status=DocumentStatus.PENDING,
                uploaded_by=document.uploaded_by,
            )

        payload = {
            "organization_id": organization_id,
            "title": "Brand Book",
            "filename": "brand.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
            "uploaded_by": uuid4(),
            "count_documents_fn": count_documents_fn,
            "create_document_fn": create_document_fn,
            "bucket_store": bucket,
        }
        payload.update(overrides)
        return await documents_use_cases.request_upload(**payload)

    run.created = created
    return run


async def test_an_upload_ticket_carries_the_presigned_url(request_upload, bucket):
    _document, url = await request_upload()

    assert url == bucket.presign_url


async def test_the_presigned_key_is_scoped_to_the_organization(
    request_upload, bucket, organization_id
):
    document, _url = await request_upload()

    key, content_type, expires_in = bucket.presigned[0]
    assert str(organization_id) in key
    assert str(document.id) in key
    assert content_type == "application/pdf"
    assert expires_in == config.UPLOAD_URL_TTL_SECONDS


async def test_the_document_starts_pending(request_upload):
    document, _url = await request_upload()

    assert document.status is DocumentStatus.PENDING


async def test_an_oversized_file_is_refused(request_upload, bucket):
    with pytest.raises(ValidationError) as exc:
        await request_upload(size_bytes=config.MAX_DOCUMENT_BYTES + 1)

    assert exc.value.code == "document_too_large"
    assert exc.value.status_code == 422
    assert bucket.presigned == []


async def test_nothing_is_created_when_the_file_is_too_large(request_upload):
    with pytest.raises(ValidationError):
        await request_upload(size_bytes=config.MAX_DOCUMENT_BYTES + 1)

    assert request_upload.created == []


async def test_a_full_organization_is_refused(request_upload):
    with pytest.raises(ConflictError) as exc:
        await request_upload(count=config.MAX_DOCUMENTS_PER_ORGANIZATION)

    assert exc.value.code == "document_limit_reached"
    assert exc.value.status_code == 409


@pytest.fixture
def complete(organization_id, bucket):
    saved = []

    async def run(document=None, uploaded_size: int | None = 4096):
        target = document if document is not None else make_document(
            organization_id=organization_id, status=DocumentStatus.PENDING
        )
        if uploaded_size is not None:
            key = keys.document_key(organization_id, target.id, target.filename)
            bucket.objects[key] = uploaded_size

        async def get_document_fn(document_id, org_id):
            if document_id == target.id and org_id == target.organization_id:
                return target
            return None

        async def save_uploaded_fn(document_id, org_id, size_bytes):
            saved.append((document_id, org_id, size_bytes))
            return make_document(
                document_id=document_id,
                organization_id=org_id,
                size_bytes=size_bytes,
                status=DocumentStatus.EXTRACTING,
            )

        return await documents_use_cases.complete_upload(
            document_id=target.id,
            organization_id=organization_id,
            get_document_fn=get_document_fn,
            save_uploaded_fn=save_uploaded_fn,
            bucket_store=bucket,
        )

    run.saved = saved
    return run


async def test_completing_moves_the_document_to_extracting(complete):
    document = await complete()

    assert document.status is DocumentStatus.EXTRACTING


async def test_the_real_uploaded_size_is_recorded(complete):
    await complete(uploaded_size=7777)

    assert complete.saved[0][2] == 7777


async def test_completing_without_an_upload_is_refused(complete):
    with pytest.raises(ConflictError) as exc:
        await complete(uploaded_size=None)

    assert exc.value.code == "document_not_uploaded"


async def test_a_file_that_lied_about_its_size_is_refused(complete):
    with pytest.raises(ValidationError) as exc:
        await complete(uploaded_size=config.MAX_DOCUMENT_BYTES + 1)

    assert exc.value.code == "document_too_large"
    assert complete.saved == []


async def test_completing_an_unknown_document_is_not_found(complete, organization_id):
    other = make_document(organization_id=uuid4())

    with pytest.raises(NotFoundError) as exc:
        await complete(document=other)

    assert exc.value.code == "document_not_found"


@pytest.fixture
def delete(organization_id, bucket):
    async def run(found: bool = True, removed: bool = True):
        document = make_document(organization_id=organization_id)

        async def get_document_fn(_document_id, _org_id):
            return document if found else None

        async def delete_document_fn(_document_id, _org_id):
            return removed

        await documents_use_cases.delete_document(
            document_id=document.id,
            organization_id=organization_id,
            get_document_fn=get_document_fn,
            delete_document_fn=delete_document_fn,
            bucket_store=bucket,
        )
        return document

    return run


async def test_deleting_removes_the_stored_object(delete, bucket, organization_id):
    document = await delete()

    assert bucket.deleted == [
        keys.document_key(organization_id, document.id, document.filename)
    ]


async def test_deleting_an_unknown_document_is_not_found(delete, bucket):
    with pytest.raises(NotFoundError) as exc:
        await delete(found=False)

    assert exc.value.code == "document_not_found"
    assert bucket.deleted == []


def test_a_document_with_real_text_is_extracted():
    assert documents_use_cases.classify("x" * 200) is DocumentStatus.EXTRACTED


def test_a_near_empty_extraction_is_unsupported_not_ready():
    assert documents_use_cases.classify("   \n  ") is DocumentStatus.UNSUPPORTED


def test_the_key_is_namespaced_per_organization():
    organization_id, document_id = uuid4(), uuid4()

    key = keys.document_key(organization_id, document_id, "brand.PDF")

    assert f"organizations/{organization_id}/documents/{document_id}.pdf" in key


def test_two_organizations_never_share_a_key():
    document_id = uuid4()

    first = keys.document_key(uuid4(), document_id, "brand.pdf")
    second = keys.document_key(uuid4(), document_id, "brand.pdf")

    assert first != second


def test_a_document_with_no_description_still_serialises():
    from src.documents import mapper

    response = mapper.domain_to_document_response(make_document(description=""))

    assert response.description == ""


def test_a_skill_with_no_description_still_serialises():
    from helpers import make_skill

    from src.skills import mapper as skills_mapper

    response = skills_mapper.domain_to_skill_response(make_skill(description=""))

    assert response.description == ""


@pytest.fixture
def update(organization_id):
    applied = []

    async def run(found: bool = True, **fields):
        async def update_document_fn(document_id, org_id, changes):
            applied.append((document_id, org_id, changes))
            return make_document(organization_id=org_id, **changes) if found else None

        return await documents_use_cases.update_document(
            document_id=uuid4(),
            organization_id=organization_id,
            update_document_fn=update_document_fn,
            **fields,
        )

    run.applied = applied
    return run


async def test_only_the_supplied_fields_are_changed(update):
    await update(description="Palette rules.")

    assert update.applied[0][2] == {"description": "Palette rules."}


async def test_both_fields_can_change_at_once(update):
    await update(title="Brand Book 2026", description="Palette rules.")

    assert update.applied[0][2] == {
        "title": "Brand Book 2026",
        "description": "Palette rules.",
    }


async def test_a_description_can_be_cleared(update):
    await update(description="")

    assert update.applied[0][2] == {"description": ""}


async def test_an_empty_patch_is_refused(update):
    with pytest.raises(ValidationError) as exc:
        await update()

    assert exc.value.code == "document_no_changes"
    assert update.applied == []


async def test_updating_an_unknown_document_is_not_found(update):
    with pytest.raises(NotFoundError) as exc:
        await update(found=False, title="Nope")

    assert exc.value.code == "document_not_found"


async def test_the_update_is_scoped_to_the_callers_organization(update, organization_id):
    await update(title="Renamed")

    assert update.applied[0][1] == organization_id
