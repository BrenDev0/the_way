from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.invitations.domain import InvitationCreate
from src.invitations.ports import (
    AcceptInvitationFn,
    CountPendingForOrganizationFn,
    CreateInvitationFn,
    GetInvitationByTokenHashFn,
    GetPendingForEmailFn,
    ListPendingForOrganizationFn,
    RevokeInvitationFn,
    RevokePendingForEmailFn,
)

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_create_invitation_fn(session: Session) -> CreateInvitationFn:
    async def create_invitation_fn(invitation: InvitationCreate):
        return await adapter.create(session, invitation)

    return create_invitation_fn


def provide_get_invitation_by_token_hash_fn(
    session: Session,
) -> GetInvitationByTokenHashFn:
    async def get_invitation_by_token_hash_fn(token_hash: str):
        return await adapter.get_by_token_hash(session, token_hash)

    return get_invitation_by_token_hash_fn


def provide_get_pending_for_email_fn(session: Session) -> GetPendingForEmailFn:
    async def get_pending_for_email_fn(organization_id: UUID, email_hash: str):
        return await adapter.get_pending_for_email(session, organization_id, email_hash)

    return get_pending_for_email_fn


def provide_list_pending_for_organization_fn(
    session: Session,
) -> ListPendingForOrganizationFn:
    async def list_pending_for_organization_fn(organization_id: UUID):
        return await adapter.list_pending_for_organization(session, organization_id)

    return list_pending_for_organization_fn


def provide_count_pending_for_organization_fn(
    session: Session,
) -> CountPendingForOrganizationFn:
    async def count_pending_for_organization_fn(organization_id: UUID):
        return await adapter.count_pending_for_organization(session, organization_id)

    return count_pending_for_organization_fn


def provide_accept_invitation_fn(session: Session) -> AcceptInvitationFn:
    async def accept_invitation_fn(invitation_id: UUID):
        return await adapter.accept(session, invitation_id)

    return accept_invitation_fn


def provide_revoke_invitation_fn(session: Session) -> RevokeInvitationFn:
    async def revoke_invitation_fn(invitation_id: UUID, organization_id: UUID):
        return await adapter.revoke(session, invitation_id, organization_id)

    return revoke_invitation_fn


def provide_revoke_pending_for_email_fn(session: Session) -> RevokePendingForEmailFn:
    async def revoke_pending_for_email_fn(organization_id: UUID, email_hash: str):
        return await adapter.revoke_pending_for_email(session, organization_id, email_hash)

    return revoke_pending_for_email_fn
