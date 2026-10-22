"""The staff panel's view across organizations, against real Postgres: the counts per
organization, the people in one, and the record kept when one is deleted."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.invitations.domain import InvitationCreate
from src.invitations.sqlalchemy import adapter as invitations_adapter
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow
from src.sessions.domain import SessionCreate
from src.sessions.sqlalchemy import adapter as sessions_adapter
from src.staff.domain import DeletedOrganizationCreate, StaffMemberCreate
from src.staff.sqlalchemy import adapter, reports
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_org(db_session, name=None, seat_limit=None):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name=name or f"Org {uuid4().hex[:6]}", seat_limit=seat_limit)
    )
    await db_session.commit()
    return organization


async def make_user(db_session, organization, role, label=None):
    """Each user is committed alone, so their created_at times differ and 'oldest' is real."""
    label = label or f"{role.value}-{uuid4().hex[:6]}"
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{label}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::x",
            role=role,
        ),
    )
    await db_session.commit()
    await asyncio.sleep(0.01)
    return user


async def seen(db_session, user, ago: timedelta):
    now = datetime.now(UTC)
    await sessions_adapter.create(
        db_session,
        SessionCreate(
            user_id=user.id,
            token_hash=f"hash-{uuid4()}",
            expires_at=now + timedelta(days=7),
            last_seen_at=now - ago,
        ),
    )
    await db_session.commit()


async def invite(db_session, organization, *, accepted=False, revoked=False, expired=False):
    invitation = await invitations_adapter.create(
        db_session,
        InvitationCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4().hex[:6]}@example.com",
            email_hash=f"dhash::{uuid4()}",
            role=Role.MEMBER,
            token_hash=f"tokenhash-{uuid4()}",
            expires_at=datetime.now(UTC) + (timedelta(days=-1) if expired else timedelta(days=7)),
        ),
    )
    if accepted:
        await invitations_adapter.accept(db_session, invitation.id)
    if revoked:
        await invitations_adapter.revoke(db_session, invitation.id, organization.id)
    await db_session.commit()
    return invitation


async def add_file(db_session, organization, project, size, status=FileStatus.READY):
    db_session.add(
        FileRow(project_id=project.id, name=f"f-{uuid4().hex[:4]}", content_type="text/plain", size_bytes=size, status=status.value)
    )
    await db_session.commit()


async def add_project(db_session, organization, owner=None):
    project = ProjectRow(organization_id=organization.id, owner_id=owner.id if owner else None, name=f"p-{uuid4().hex[:5]}")
    db_session.add(project)
    await db_session.commit()
    return project


def by_id(summaries):
    return {summary.id: summary for summary in summaries}


# --- the list --------------------------------------------------------------------------------


async def test_an_organization_is_counted_by_its_people_invitations_files_and_activity(db_session):
    organization = await make_org(db_session, name="Counted Co", seat_limit=7)
    owner = await make_user(db_session, organization, Role.OWNER, "boss")
    admin = await make_user(db_session, organization, Role.ADMIN)
    await make_user(db_session, organization, Role.MEMBER)
    await seen(db_session, owner, timedelta(days=3))
    await seen(db_session, admin, timedelta(minutes=5))
    await invite(db_session, organization)  # open
    await invite(db_session, organization, accepted=True)
    await invite(db_session, organization, revoked=True)
    await invite(db_session, organization, expired=True)
    project = await add_project(db_session, organization, owner)
    await add_file(db_session, organization, project, 1_000)
    await add_file(db_session, organization, project, 2_500)
    await add_file(db_session, organization, project, 9_999, status=FileStatus.PENDING)

    summary = by_id(await reports.list_summaries(db_session))[organization.id]

    assert summary.name == "Counted Co"
    assert summary.seat_limit == 7
    assert summary.members == 3
    assert summary.pending_invitations == 1  # not the accepted, revoked or expired ones
    assert summary.files == 2 and summary.bytes == 3_500  # only what finished uploading
    assert summary.owner_encrypted_email == "enc::boss@example.com"
    # the most recent sign-in activity of anyone in it
    assert summary.last_seen_at is not None
    assert datetime.now(UTC) - summary.last_seen_at < timedelta(minutes=10)


async def test_an_empty_organization_is_all_zeros_and_has_never_been_seen(db_session):
    organization = await make_org(db_session)

    summary = by_id(await reports.list_summaries(db_session))[organization.id]

    assert (summary.members, summary.pending_invitations, summary.files, summary.bytes) == (0, 0, 0, 0)
    assert summary.owner_encrypted_email is None
    assert summary.last_seen_at is None


async def test_one_organizations_numbers_never_include_anothers(db_session):
    first = await make_org(db_session)
    second = await make_org(db_session)
    await make_user(db_session, first, Role.OWNER)
    await make_user(db_session, second, Role.OWNER)
    await make_user(db_session, second, Role.MEMBER)
    await invite(db_session, second)
    await add_file(db_session, second, await add_project(db_session, second), 700)

    found = by_id(await reports.list_summaries(db_session))

    assert (found[first.id].members, found[first.id].pending_invitations, found[first.id].files) == (1, 0, 0)
    assert (found[second.id].members, found[second.id].pending_invitations, found[second.id].files) == (2, 1, 1)


async def test_the_oldest_owner_is_the_one_named_when_there_are_two(db_session):
    organization = await make_org(db_session)
    await make_user(db_session, organization, Role.OWNER, "first")
    await make_user(db_session, organization, Role.OWNER, "second")

    summary = by_id(await reports.list_summaries(db_session))[organization.id]

    assert summary.owner_encrypted_email == "enc::first@example.com"


async def test_the_newest_organization_is_listed_first(db_session):
    older = await make_org(db_session)
    await asyncio.sleep(0.01)
    newer = await make_org(db_session)

    listed = [summary.id for summary in await reports.list_summaries(db_session)]

    assert listed.index(newer.id) < listed.index(older.id)


async def test_one_organization_can_be_read_alone_and_an_unknown_one_is_none(db_session):
    organization = await make_org(db_session, name="Alone Ltd")
    await make_user(db_session, organization, Role.OWNER)

    found = await reports.get_summary(db_session, organization.id)

    assert found is not None and found.name == "Alone Ltd" and found.members == 1
    assert await reports.get_summary(db_session, uuid4()) is None


# --- one organization's people ----------------------------------------------------------------------


async def test_the_people_come_owners_first_then_admins_then_members_oldest_first(db_session):
    organization = await make_org(db_session)
    member_a = await make_user(db_session, organization, Role.MEMBER, "member-a")
    admin = await make_user(db_session, organization, Role.ADMIN, "admin")
    member_b = await make_user(db_session, organization, Role.MEMBER, "member-b")
    owner = await make_user(db_session, organization, Role.OWNER, "owner")

    members = await reports.list_members(db_session, organization.id)

    assert [m.id for m in members] == [owner.id, admin.id, member_a.id, member_b.id]
    assert [m.role for m in members] == [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.MEMBER]
    assert members[0].encrypted_email == "enc::owner@example.com"


async def test_each_person_shows_when_they_were_last_seen_on_any_device(db_session):
    organization = await make_org(db_session)
    active = await make_user(db_session, organization, Role.OWNER)
    never = await make_user(db_session, organization, Role.MEMBER)
    await seen(db_session, active, timedelta(days=10))
    await seen(db_session, active, timedelta(hours=1))  # a second device, more recent

    members = {m.id: m for m in await reports.list_members(db_session, organization.id)}

    assert datetime.now(UTC) - members[active.id].last_seen_at < timedelta(hours=2)
    assert members[never.id].last_seen_at is None


async def test_only_this_organizations_people_are_listed(db_session):
    mine = await make_org(db_session)
    other = await make_org(db_session)
    me = await make_user(db_session, mine, Role.OWNER)
    await make_user(db_session, other, Role.OWNER)

    assert [m.id for m in await reports.list_members(db_session, mine.id)] == [me.id]
    assert await reports.list_members(db_session, uuid4()) == []


# --- the record of deleted organizations -----------------------------------------------------------------


async def test_a_deleted_organization_is_kept_on_record_and_listed_newest_first(db_session):
    staff = await adapter.create_member(
        db_session, StaffMemberCreate(encrypted_email="enc::ana@x.example", email_hash=f"dhash::{uuid4()}", password_hash="p")
    )
    await db_session.commit()

    def record(name, left):
        return DeletedOrganizationCreate(
            organization_id=uuid4(), organization_name=name, deleted_by=staff.id,
            deleted_by_encrypted_email="enc::ana@x.example", members=3, files=10, bytes=12_345,
            files_removed=10, files_left=left,
        )

    first = await adapter.record_deleted_organization(db_session, record("First Co", 0))
    await db_session.commit()
    await asyncio.sleep(0.01)
    second = await adapter.record_deleted_organization(db_session, record("Second Co", None))
    await db_session.commit()

    listed = [r.id for r in await adapter.list_deleted_organizations(db_session)]

    assert listed.index(second.id) < listed.index(first.id)
    assert (first.members, first.files, first.bytes, first.files_removed, first.files_left) == (3, 10, 12_345, 10, 0)
    assert second.files_left is None  # unknown is kept distinct from zero


async def test_the_record_outlives_the_staff_member_and_the_organization_it_describes(db_session):
    """No foreign key points at the organization (it is gone), and the staff member's
    link goes empty if they are removed, but the encrypted email still says who."""
    staff = await adapter.create_member(
        db_session, StaffMemberCreate(encrypted_email="enc::gone@x.example", email_hash=f"dhash::{uuid4()}", password_hash="p")
    )
    organization = await make_org(db_session)
    await db_session.commit()
    saved = await adapter.record_deleted_organization(
        db_session,
        DeletedOrganizationCreate(
            organization_id=organization.id, organization_name="Gone Co", deleted_by=staff.id,
            deleted_by_encrypted_email="enc::gone@x.example", members=1, files=0, bytes=0, files_removed=0, files_left=0,
        ),
    )
    await db_session.commit()

    await organizations_adapter.delete_by_id(db_session, organization.id)
    from sqlalchemy import delete

    from src.staff.sqlalchemy.models import StaffMemberRow

    await db_session.execute(delete(StaffMemberRow).where(StaffMemberRow.id == staff.id))
    await db_session.commit()

    kept = next(r for r in await adapter.list_deleted_organizations(db_session) if r.id == saved.id)
    assert kept.organization_name == "Gone Co"
    assert kept.organization_id == organization.id
    assert kept.deleted_by is None
    assert kept.deleted_by_encrypted_email == "enc::gone@x.example"
