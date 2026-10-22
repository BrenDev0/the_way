"""Sign-in and sign-out for Xplorers staff: the session travels in an httpOnly cookie of
its own, apart from every customer's."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError
from src.fastapi import dependencies as api_dependencies
from src.sessions.config import SessionCookieConfig
from src.sessions.tokens import SessionTokenService
from src.staff.domain import StaffMember
from src.staff.ports import (
    CreateStaffSessionFn,
    GetStaffMemberByEmailHashFn,
    RevokeStaffSessionByTokenHashFn,
)
from src.staff.use_cases import auth as auth_use_cases

from .. import dependencies as staff_dependencies
from ..schemas import StaffLoginRequest, StaffLogoutResponse, StaffResponse

router = APIRouter(tags=["staff"])


@router.post("/login", response_model=StaffResponse)
async def login_staff_route(
    payload: StaffLoginRequest,
    response: Response,
    get_staff_member_by_email_hash_fn: Annotated[
        GetStaffMemberByEmailHashFn,
        Depends(staff_dependencies.provide_get_staff_member_by_email_hash_fn),
    ],
    create_staff_session_fn: Annotated[
        CreateStaffSessionFn,
        Depends(staff_dependencies.provide_create_staff_session_fn),
    ],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    encryption_service: Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)],
    token_service: Annotated[SessionTokenService, Depends(staff_dependencies.get_staff_token_service)],
    cookie_config: Annotated[SessionCookieConfig, Depends(staff_dependencies.get_staff_cookie_config)],
) -> StaffResponse:
    staff, session_token = await auth_use_cases.login_staff(
        email=payload.email,
        password=payload.password,
        get_staff_member_by_email_hash_fn=get_staff_member_by_email_hash_fn,
        hashing_service=hashing_service,
        create_staff_session_fn=create_staff_session_fn,
        token_service=token_service,
    )

    response.set_cookie(
        key=cookie_config.name,
        value=session_token,
        max_age=cookie_config.max_age_seconds,
        expires=cookie_config.max_age_seconds,
        path=cookie_config.path,
        secure=cookie_config.secure,
        httponly=cookie_config.httponly,
        samesite=cookie_config.samesite,
    )
    return StaffResponse.from_domain(staff, email=encryption_service.decrypt(staff.encrypted_email))


@router.get("/me", response_model=StaffResponse)
async def current_staff_route(
    staff: Annotated[StaffMember, Depends(staff_dependencies.get_current_staff)],
    encryption_service: Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)],
) -> StaffResponse:
    return StaffResponse.from_domain(staff, email=encryption_service.decrypt(staff.encrypted_email))


@router.post("/logout", response_model=StaffLogoutResponse)
async def logout_staff_route(
    request: Request,
    response: Response,
    revoke_staff_session_by_token_hash_fn: Annotated[
        RevokeStaffSessionByTokenHashFn,
        Depends(staff_dependencies.provide_revoke_staff_session_by_token_hash_fn),
    ],
    token_service: Annotated[SessionTokenService, Depends(staff_dependencies.get_staff_token_service)],
    cookie_config: Annotated[SessionCookieConfig, Depends(staff_dependencies.get_staff_cookie_config)],
) -> StaffLogoutResponse:
    token = request.cookies.get(cookie_config.name)
    if not token:
        raise AuthenticationError(message="Missing session", code="missing_session")

    await auth_use_cases.logout_staff(
        token=token,
        revoke_staff_session_by_token_hash_fn=revoke_staff_session_by_token_hash_fn,
        token_service=token_service,
    )

    response.delete_cookie(
        key=cookie_config.name,
        path=cookie_config.path,
        secure=cookie_config.secure,
        httponly=cookie_config.httponly,
        samesite=cookie_config.samesite,
    )
    return StaffLogoutResponse(detail="Logged out")
