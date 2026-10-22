from dataclasses import replace
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.core.bucket.ports import BucketStore
from src.core.exceptions import AuthenticationError
from src.fastapi import dependencies as api_dependencies
from src.organizations import files as organization_files
from src.organizations.domain import FilesPurged
from src.sessions.config import SessionCookieConfig
from src.sessions.tokens import SessionTokenService
from src.staff import config
from src.staff.domain import (
    DeletedOrganizationCreate,
    OwnerInvitationCreate,
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)
from src.staff.ports import (
    ClaimOwnerInvitationFn,
    CreateOwnerInvitationFn,
    CreateStaffMemberFn,
    CreateStaffSessionFn,
    GetOrganizationSummaryFn,
    GetOwnerInvitationByTokenHashFn,
    GetStaffMemberByEmailHashFn,
    GetStaffMemberByIdFn,
    GetStaffSessionByTokenHashFn,
    ListDeletedOrganizationsFn,
    ListOrganizationMembersFn,
    ListOrganizationSummariesFn,
    ListOwnerInvitationsFn,
    PurgeOrganizationFilesFn,
    RecordDeletedOrganizationFn,
    RevokeOwnerInvitationFn,
    RevokePendingOwnerInvitationsForEmailFn,
    RevokeStaffSessionByTokenHashFn,
    TouchStaffSessionFn,
)
from src.staff.use_cases import auth as auth_use_cases

from ..sqlalchemy import adapter, reports

Session = Annotated[AsyncSession, Depends(api_dependencies.get_db_session)]


def get_staff_token_service() -> SessionTokenService:
    """Staff sessions are shorter than customers': the same token mechanics, its own window."""
    return SessionTokenService(session_ttl=timedelta(seconds=config.STAFF_SESSION_TTL_SECONDS))


def get_staff_cookie_config(
    base: Annotated[SessionCookieConfig, Depends(api_dependencies.get_session_cookie_config)],
) -> SessionCookieConfig:
    """The customers' cookie settings with a name and lifetime of their own, so a staff
    session and a customer session never replace each other in one browser."""
    return replace(
        base,
        name=config.STAFF_SESSION_COOKIE_NAME,
        max_age_seconds=config.STAFF_SESSION_TTL_SECONDS,
    )


def provide_create_staff_member_fn(session: Session) -> CreateStaffMemberFn:
    async def create_staff_member_fn(member: StaffMemberCreate):
        return await adapter.create_member(session, member)

    return create_staff_member_fn


def provide_get_staff_member_by_id_fn(session: Session) -> GetStaffMemberByIdFn:
    async def get_staff_member_by_id_fn(staff_id: UUID):
        return await adapter.get_member_by_id(session, staff_id)

    return get_staff_member_by_id_fn


def provide_get_staff_member_by_email_hash_fn(session: Session) -> GetStaffMemberByEmailHashFn:
    async def get_staff_member_by_email_hash_fn(email_hash: str):
        return await adapter.get_member_by_email_hash(session, email_hash)

    return get_staff_member_by_email_hash_fn


def provide_create_staff_session_fn(session: Session) -> CreateStaffSessionFn:
    async def create_staff_session_fn(staff_session: StaffSessionCreate):
        return await adapter.create_session(session, staff_session)

    return create_staff_session_fn


def provide_get_staff_session_by_token_hash_fn(session: Session) -> GetStaffSessionByTokenHashFn:
    async def get_staff_session_by_token_hash_fn(token_hash: str):
        return await adapter.get_session_by_token_hash(session, token_hash)

    return get_staff_session_by_token_hash_fn


def provide_touch_staff_session_fn(session: Session) -> TouchStaffSessionFn:
    async def touch_staff_session_fn(session_id: UUID):
        return await adapter.touch_session(session, session_id)

    return touch_staff_session_fn


def provide_revoke_staff_session_by_token_hash_fn(session: Session) -> RevokeStaffSessionByTokenHashFn:
    async def revoke_staff_session_by_token_hash_fn(token_hash: str):
        return await adapter.revoke_session_by_token_hash(session, token_hash)

    return revoke_staff_session_by_token_hash_fn


def provide_create_owner_invitation_fn(session: Session) -> CreateOwnerInvitationFn:
    async def create_owner_invitation_fn(invitation: OwnerInvitationCreate):
        return await adapter.create_invitation(session, invitation)

    return create_owner_invitation_fn


def provide_get_owner_invitation_by_token_hash_fn(session: Session) -> GetOwnerInvitationByTokenHashFn:
    async def get_owner_invitation_by_token_hash_fn(token_hash: str):
        return await adapter.get_invitation_by_token_hash(session, token_hash)

    return get_owner_invitation_by_token_hash_fn


def provide_list_owner_invitations_fn(session: Session) -> ListOwnerInvitationsFn:
    async def list_owner_invitations_fn():
        return await adapter.list_invitations(session)

    return list_owner_invitations_fn


def provide_claim_owner_invitation_fn(session: Session) -> ClaimOwnerInvitationFn:
    async def claim_owner_invitation_fn(invitation_id: UUID, organization_id: UUID):
        return await adapter.claim_invitation(session, invitation_id, organization_id)

    return claim_owner_invitation_fn


def provide_revoke_owner_invitation_fn(session: Session) -> RevokeOwnerInvitationFn:
    async def revoke_owner_invitation_fn(invitation_id: UUID):
        return await adapter.revoke_invitation(session, invitation_id)

    return revoke_owner_invitation_fn


def provide_revoke_pending_owner_invitations_for_email_fn(
    session: Session,
) -> RevokePendingOwnerInvitationsForEmailFn:
    async def revoke_pending_for_email_fn(email_hash: str):
        return await adapter.revoke_pending_invitations_for_email(session, email_hash)

    return revoke_pending_for_email_fn


def provide_list_organization_summaries_fn(session: Session) -> ListOrganizationSummariesFn:
    async def list_organization_summaries_fn():
        return await reports.list_summaries(session)

    return list_organization_summaries_fn


def provide_get_organization_summary_fn(session: Session) -> GetOrganizationSummaryFn:
    async def get_organization_summary_fn(organization_id: UUID):
        return await reports.get_summary(session, organization_id)

    return get_organization_summary_fn


def provide_list_organization_members_fn(session: Session) -> ListOrganizationMembersFn:
    async def list_organization_members_fn(organization_id: UUID):
        return await reports.list_members(session, organization_id)

    return list_organization_members_fn


def provide_record_deleted_organization_fn(session: Session) -> RecordDeletedOrganizationFn:
    async def record_deleted_organization_fn(record: DeletedOrganizationCreate):
        return await adapter.record_deleted_organization(session, record)

    return record_deleted_organization_fn


def provide_list_deleted_organizations_fn(session: Session) -> ListDeletedOrganizationsFn:
    async def list_deleted_organizations_fn():
        return await adapter.list_deleted_organizations(session)

    return list_deleted_organizations_fn


def get_optional_bucket_store(request: Request) -> BucketStore | None:
    """The file store, or None where none is configured (nothing was ever stored then)."""
    return getattr(request.app.state, "bucket_store", None)


def provide_purge_organization_files_fn(
    bucket: Annotated[BucketStore | None, Depends(get_optional_bucket_store)],
) -> PurgeOrganizationFilesFn:
    async def purge_organization_files_fn(organization_id: UUID) -> FilesPurged:
        if bucket is None:
            return FilesPurged(removed=0, failed=0)
        return await organization_files.purge_files(bucket, organization_id)

    return purge_organization_files_fn


async def get_current_staff_session(
    request: Request,
    get_staff_session_by_token_hash_fn: Annotated[
        GetStaffSessionByTokenHashFn,
        Depends(provide_get_staff_session_by_token_hash_fn),
    ],
    touch_staff_session_fn: Annotated[TouchStaffSessionFn, Depends(provide_touch_staff_session_fn)],
    token_service: Annotated[SessionTokenService, Depends(get_staff_token_service)],
    cookie_config: Annotated[SessionCookieConfig, Depends(get_staff_cookie_config)],
) -> StaffSession:
    token = request.cookies.get(cookie_config.name)
    if not token:
        raise AuthenticationError(message="Not authenticated", code="not_authenticated")

    session = await auth_use_cases.resolve_staff_session(
        token=token,
        get_staff_session_by_token_hash_fn=get_staff_session_by_token_hash_fn,
        touch_staff_session_fn=touch_staff_session_fn,
        token_service=token_service,
    )
    if session is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")
    return session


async def get_current_staff(
    session: Annotated[StaffSession, Depends(get_current_staff_session)],
    get_staff_member_by_id_fn: Annotated[GetStaffMemberByIdFn, Depends(provide_get_staff_member_by_id_fn)],
) -> StaffMember:
    return await auth_use_cases.get_staff_member(session, get_staff_member_by_id_fn)
