"""What staff can read about every organization, and the rules for deleting one."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from helpers import FakeCacheStore

from src.core.bucket.domain import BucketError
from src.core.exceptions import NotFoundError, ValidationError
from src.invitations.domain import Invitation
from src.organizations import cache as organization_cache
from src.organizations.domain import FilesPurged
from src.staff.domain import (
    DeletedOrganization,
    DeletedOrganizationCreate,
    OrganizationMember,
    OrganizationSummary,
    StaffMember,
)
from src.staff.use_cases import organizations as use_cases
from src.users.domain import Role

NAME = "Acme Inc"


def make_staff() -> StaffMember:
    return StaffMember(
        id=uuid4(),
        encrypted_email="enc::ana@xplorers.example",
        email_hash="dhash::ana@xplorers.example",
        password_hash="pwhash::x",
        created_at=datetime.now(UTC),
    )


def make_summary(organization_id: UUID | None = None, *, name: str = NAME, members: int = 4, files: int = 12, size: int = 5_000):
    return OrganizationSummary(
        id=organization_id or uuid4(),
        name=name,
        seat_limit=10,
        created_at=datetime.now(UTC),
        members=members,
        pending_invitations=1,
        owner_encrypted_email="enc::owner@acme.example",
        files=files,
        bytes=size,
        last_seen_at=None,
    )


class Scenario:
    """The ports of a deletion, recording what was called and in what order."""

    def __init__(self, summary: OrganizationSummary | None, *, purge: FilesPurged | BucketError | None = None):
        self.summary = summary
        self.calls: list[str] = []
        self.recorded: list[DeletedOrganizationCreate] = []
        self.deleted: list[UUID] = []
        self.purged: list[UUID] = []
        self.cache = FakeCacheStore()
        self._purge = purge if purge is not None else FilesPurged(removed=12, failed=0)

    async def get_summary(self, organization_id: UUID):
        self.calls.append("read")
        return self.summary

    async def delete(self, organization_id: UUID) -> bool:
        self.calls.append("delete rows")
        self.deleted.append(organization_id)
        return True

    async def purge(self, organization_id: UUID) -> FilesPurged:
        self.calls.append("purge files")
        self.purged.append(organization_id)
        if isinstance(self._purge, BucketError):
            raise self._purge
        return self._purge

    async def record(self, record: DeletedOrganizationCreate) -> DeletedOrganization:
        self.calls.append("record")
        self.recorded.append(record)
        return DeletedOrganization(id=uuid4(), created_at=datetime.now(UTC), **record.__dict__)

    async def run(self, confirmation: str, staff: StaffMember | None = None, organization_id: UUID | None = None):
        return await use_cases.delete_organization(
            staff=staff or make_staff(),
            organization_id=organization_id or (self.summary.id if self.summary else uuid4()),
            confirmation=confirmation,
            get_organization_summary_fn=self.get_summary,
            delete_organization_by_id_fn=self.delete,
            cache_store=self.cache,
            purge_organization_files_fn=self.purge,
            record_deleted_organization_fn=self.record,
        )


# --- reading -------------------------------------------------------------------------------------


async def test_the_list_is_what_the_query_gives():
    summaries = [make_summary(), make_summary()]

    async def list_all():
        return summaries

    assert list(await use_cases.list_organizations(list_all)) == summaries


async def test_one_organization_comes_with_its_people_and_its_open_invitations():
    summary = make_summary()
    member = OrganizationMember(
        id=uuid4(), encrypted_email="enc::a@acme.example", role=Role.OWNER, created_at=datetime.now(UTC), last_seen_at=None
    )
    invitation = Invitation(
        id=uuid4(), organization_id=summary.id, encrypted_email="enc::new@acme.example", email_hash="h",
        role=Role.MEMBER, expires_at=datetime.now(UTC), accepted_at=None, revoked_at=None, invited_by=None,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )

    async def get_summary(organization_id):
        return summary

    async def members(organization_id):
        return [member]

    async def pending(organization_id):
        return [invitation]

    detail = await use_cases.get_organization(summary.id, get_summary, members, pending)

    assert detail.summary is summary
    assert list(detail.members) == [member]
    assert list(detail.pending_invitations) == [invitation]


async def test_an_unknown_organization_is_not_found_and_nothing_else_is_read():
    asked: list[str] = []

    async def none(organization_id):
        return None

    async def members(organization_id):
        asked.append("members")
        return []

    async def pending(organization_id):
        asked.append("pending")
        return []

    with pytest.raises(NotFoundError) as exc:
        await use_cases.get_organization(uuid4(), none, members, pending)

    assert exc.value.code == "organization_not_found"
    assert asked == []


# --- deleting: confirming ------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["", "acme inc", "ACME INC", "Acme", "Acme Inc.", "Acme  Inc", "something else"])
async def test_anything_but_the_exact_name_deletes_nothing(typed):
    scenario = Scenario(make_summary())

    with pytest.raises(ValidationError) as exc:
        await scenario.run(typed)

    assert exc.value.code == "confirmation_mismatch"
    assert scenario.calls == ["read"]  # nothing was deleted, purged or recorded
    assert scenario.recorded == []


async def test_the_exact_name_deletes_it():
    scenario = Scenario(make_summary())

    record = await scenario.run(NAME)

    assert scenario.deleted == [scenario.summary.id]
    assert record.organization_name == NAME


async def test_stray_spaces_around_the_typed_name_are_forgiven_and_nothing_else():
    scenario = Scenario(make_summary())

    await scenario.run(f"  {NAME}\n")

    assert scenario.deleted == [scenario.summary.id]


async def test_an_unknown_organization_is_not_found_before_anything_is_asked_of_the_bucket():
    scenario = Scenario(None)

    with pytest.raises(NotFoundError):
        await scenario.run(NAME)

    assert scenario.calls == ["read"]


# --- deleting: what happens, and in what order ------------------------------------------------------


async def test_the_rows_go_first_then_the_files_then_the_record_is_written():
    """If the rows went last, a failure would leave an organization whose files are gone but
    which still exists to be used."""
    scenario = Scenario(make_summary())

    await scenario.run(NAME)

    assert scenario.calls == ["read", "delete rows", "purge files", "record"]


async def test_the_files_purged_are_the_organizations_own():
    scenario = Scenario(make_summary())

    await scenario.run(NAME)

    assert scenario.purged == [scenario.summary.id]


async def test_the_record_says_who_what_and_how_much():
    scenario = Scenario(make_summary(name=NAME, members=4, files=12, size=5_000))
    staff = make_staff()

    record = await scenario.run(NAME, staff)

    saved = scenario.recorded[0]
    assert saved.organization_id == scenario.summary.id
    assert saved.organization_name == NAME
    assert saved.deleted_by == staff.id
    assert saved.deleted_by_encrypted_email == staff.encrypted_email  # encrypted, as it is stored
    assert (saved.members, saved.files, saved.bytes) == (4, 12, 5_000)
    assert (saved.files_removed, saved.files_left) == (12, 0)
    assert record.deleted_by == staff.id


async def test_the_organizations_cached_copy_is_cleared():
    scenario = Scenario(make_summary())
    key = organization_cache.build_organization_cache_key(
        organization_cache.OrganizationCacheKey.BY_ID, scenario.summary.id
    )
    scenario.cache.data[key] = {"name": NAME}

    await scenario.run(NAME)

    assert key not in scenario.cache.data


# --- deleting: when the bucket does not cooperate --------------------------------------------------------


async def test_files_that_could_not_be_deleted_are_recorded_as_left_behind():
    scenario = Scenario(make_summary(), purge=FilesPurged(removed=9, failed=3))

    record = await scenario.run(NAME)

    assert scenario.deleted  # the organization is gone regardless
    assert (record.files_removed, record.files_left) == (9, 3)


async def test_a_bucket_that_cannot_be_reached_does_not_stop_the_deletion():
    scenario = Scenario(make_summary(), purge=BucketError("signature does not match"))

    record = await scenario.run(NAME)

    assert scenario.deleted == [scenario.summary.id]
    assert scenario.calls == ["read", "delete rows", "purge files", "record"]
    # None says nobody can tell what is left, not that nothing is
    assert (record.files_removed, record.files_left) == (0, None)


async def test_the_bucket_failure_is_logged_with_the_organization_it_was_for(caplog):
    scenario = Scenario(make_summary(), purge=BucketError("signature does not match"))

    with caplog.at_level("WARNING"):
        await scenario.run(NAME)

    assert str(scenario.summary.id) in caplog.text
    assert "signature does not match" in caplog.text
