from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth.fastapi.schemas import (
    RequestRegistrationVerificationRequest,
    RequestRegistrationVerificationResponse,
    UserRegistrationRequest,
)
from src.auth.use_cases import registration as registration_use_cases
from src.core.cache.ports import CacheStore
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.fastapi import dependencies as api_dependencies
from src.organizations.fastapi import dependencies as organizations_dependencies
from src.organizations.ports import CreateOrganizationFn
from src.users.fastapi import dependencies as users_dependencies
from src.users.fastapi.schemas import UserResponse
from src.users.ports import CreateUserFn, GetUserByEmailHashFn

router = APIRouter(tags=["auth"])


@router.post(
    "/register/request-verification",
    response_model=RequestRegistrationVerificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_registration_verification_route(
    payload: RequestRegistrationVerificationRequest,
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    email_sender: Annotated[EmailSender, Depends(api_dependencies.get_email_sender)],
) -> RequestRegistrationVerificationResponse:
    expires_at = await registration_use_cases.send_registration_verification_code(
        email=payload.email,
        cache_store=cache_store,
        hashing_service=hashing_service,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        email_sender=email_sender,
    )
    return RequestRegistrationVerificationResponse(
        detail="Verification code sent",
        expires_at=expires_at,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user_route(
    payload: UserRegistrationRequest,
    create_organization_fn: Annotated[
        CreateOrganizationFn,
        Depends(organizations_dependencies.provide_create_organization_fn),
    ],
    create_user_fn: Annotated[CreateUserFn, Depends(users_dependencies.provide_create_user_fn)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    encryption_service: Annotated[
        EncryptionService,
        Depends(api_dependencies.get_encryption_service),
    ],
) -> UserResponse:
    user = await registration_use_cases.register_user(
        organization_name=payload.organization_name,
        email=payload.email,
        password=payload.password,
        verification_code=payload.verification_code,
        create_organization_fn=create_organization_fn,
        create_user_fn=create_user_fn,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        cache_store=cache_store,
        hashing_service=hashing_service,
        encryption_service=encryption_service,
    )
    return UserResponse.from_domain(
        user,
        email=encryption_service.decrypt(user.encrypted_email),
        setup_complete=False,
    )
