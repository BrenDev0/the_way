from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.bucket.ports import BucketStore
from src.users.domain import Role, User

from . import config, mapper
from . import dependencies as documents_dependencies
from . import use_cases as documents_use_cases
from .ports import (
    CountDocumentsFn,
    CountUntrainedFn,
    CreateDocumentFn,
    DeleteDocumentFn,
    GetDocumentFn,
    ListDocumentsForOrganizationFn,
    SaveUploadedFn,
    UpdateDocumentFn,
)
from .schemas import (
    DeleteDocumentResponse,
    DocumentResponse,
    RequestUploadRequest,
    TrainDocumentsResponse,
    UpdateDocumentRequest,
    UploadTicketResponse,
)
from .tasks import ingest_document, train_documents

router = APIRouter(tags=["documents"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
]
Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]


@router.post("", response_model=UploadTicketResponse, status_code=status.HTTP_201_CREATED)
async def request_upload_route(
    payload: RequestUploadRequest,
    current_user: CurrentUser,
    bucket_store: Bucket,
    count_documents_fn: Annotated[
        CountDocumentsFn,
        Depends(documents_dependencies.provide_count_documents_fn),
    ],
    create_document_fn: Annotated[
        CreateDocumentFn,
        Depends(documents_dependencies.provide_create_document_fn),
    ],
) -> UploadTicketResponse:
    document, upload_url = await documents_use_cases.request_upload(
        organization_id=current_user.organization_id,
        title=payload.title,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        description=payload.description,
        uploaded_by=current_user.id,
        count_documents_fn=count_documents_fn,
        create_document_fn=create_document_fn,
        bucket_store=bucket_store,
    )
    return UploadTicketResponse(
        document=mapper.domain_to_document_response(document),
        upload_url=upload_url,
        expires_in_seconds=config.UPLOAD_URL_TTL_SECONDS,
    )


@router.post(
    "/{document_id}/complete",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_upload_route(
    document_id: UUID,
    current_user: CurrentUser,
    bucket_store: Bucket,
    get_document_fn: Annotated[
        GetDocumentFn,
        Depends(documents_dependencies.provide_get_document_fn),
    ],
    save_uploaded_fn: Annotated[
        SaveUploadedFn,
        Depends(documents_dependencies.provide_save_uploaded_fn),
    ],
) -> DocumentResponse:
    document = await documents_use_cases.complete_upload(
        document_id=document_id,
        organization_id=current_user.organization_id,
        get_document_fn=get_document_fn,
        save_uploaded_fn=save_uploaded_fn,
        bucket_store=bucket_store,
    )

    await ingest_document.kiq(document.id)  # type: ignore[call-overload]

    return mapper.domain_to_document_response(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents_route(
    current_user: CurrentUser,
    list_documents_for_organization_fn: Annotated[
        ListDocumentsForOrganizationFn,
        Depends(documents_dependencies.provide_list_documents_for_organization_fn),
    ],
) -> list[DocumentResponse]:
    documents = await documents_use_cases.list_documents(
        organization_id=current_user.organization_id,
        list_documents_for_organization_fn=list_documents_for_organization_fn,
    )
    return [mapper.domain_to_document_response(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document_route(
    document_id: UUID,
    current_user: CurrentUser,
    get_document_fn: Annotated[
        GetDocumentFn,
        Depends(documents_dependencies.provide_get_document_fn),
    ],
) -> DocumentResponse:
    document = await documents_use_cases.get_document(
        document_id=document_id,
        organization_id=current_user.organization_id,
        get_document_fn=get_document_fn,
    )
    return mapper.domain_to_document_response(document)


@router.delete("/{document_id}", response_model=DeleteDocumentResponse)
async def delete_document_route(
    document_id: UUID,
    current_user: CurrentUser,
    bucket_store: Bucket,
    get_document_fn: Annotated[
        GetDocumentFn,
        Depends(documents_dependencies.provide_get_document_fn),
    ],
    delete_document_fn: Annotated[
        DeleteDocumentFn,
        Depends(documents_dependencies.provide_delete_document_fn),
    ],
) -> DeleteDocumentResponse:
    await documents_use_cases.delete_document(
        document_id=document_id,
        organization_id=current_user.organization_id,
        get_document_fn=get_document_fn,
        delete_document_fn=delete_document_fn,
        bucket_store=bucket_store,
    )
    return DeleteDocumentResponse(detail="Document deleted")


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document_route(
    document_id: UUID,
    payload: UpdateDocumentRequest,
    current_user: CurrentUser,
    update_document_fn: Annotated[
        UpdateDocumentFn,
        Depends(documents_dependencies.provide_update_document_fn),
    ],
) -> DocumentResponse:
    document = await documents_use_cases.update_document(
        document_id=document_id,
        organization_id=current_user.organization_id,
        title=payload.title,
        description=payload.description,
        update_document_fn=update_document_fn,
    )
    return mapper.domain_to_document_response(document)


@router.post(
    "/train",
    response_model=TrainDocumentsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def train_documents_route(
    current_user: CurrentUser,
    count_untrained_fn: Annotated[
        CountUntrainedFn,
        Depends(documents_dependencies.provide_count_untrained_fn),
    ],
) -> TrainDocumentsResponse:
    queued = await documents_use_cases.count_untrained(
        organization_id=current_user.organization_id,
        count_untrained_fn=count_untrained_fn,
    )

    await train_documents.kiq(  # type: ignore[call-overload]
        current_user.organization_id, current_user.id
    )

    return TrainDocumentsResponse(
        detail="Training started", queued=queued
    )
