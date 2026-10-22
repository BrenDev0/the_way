"""Deleting everything an organization has in the bucket: it removes that organization's
files and nothing else."""

from uuid import uuid4

import pytest
from helpers import BrokenBucketStore, FakeBucketStore

from src.core.bucket.domain import BucketError
from src.core.settings.shared import settings
from src.documents import keys as document_keys
from src.organizations import files, keys
from src.organizations.domain import FilesPurged
from src.projects import keys as project_keys


def put(bucket: FakeBucketStore, key: str) -> str:
    bucket.objects[key] = 10
    return key


# --- where an organization's files are ---------------------------------------------------------


def test_the_prefix_ends_with_a_slash_so_no_organizations_prefix_starts_another():
    organization_id = uuid4()

    assert keys.organization_prefix(organization_id).endswith(f"/organizations/{organization_id}/")


def test_the_prefix_follows_the_buckets_own_prefix(monkeypatch):
    organization_id = uuid4()
    monkeypatch.setattr(settings, "BUCKET_PREFIX", "/custom/root/")
    assert keys.organization_prefix(organization_id) == f"custom/root/organizations/{organization_id}/"

    monkeypatch.setattr(settings, "BUCKET_PREFIX", "")
    assert keys.organization_prefix(organization_id) == f"organizations/{organization_id}/"


@pytest.mark.parametrize("bucket_prefix", ["the_way", "", "/a/b/"])
def test_everything_the_app_stores_for_an_organization_is_under_its_prefix(monkeypatch, bucket_prefix):
    """The purge deletes by this prefix. If a new kind of file were keyed anywhere else it
    would survive an organization's deletion, so the two builders that exist are pinned."""
    monkeypatch.setattr(settings, "BUCKET_PREFIX", bucket_prefix)
    organization_id = uuid4()
    prefix = keys.organization_prefix(organization_id)

    assert project_keys.file_key(organization_id, uuid4()).startswith(prefix)
    assert document_keys.document_key(organization_id, uuid4(), "brand.pdf").startswith(prefix)


# --- the purge ---------------------------------------------------------------------------------


async def test_it_removes_every_file_of_the_organization():
    organization_id = uuid4()
    bucket = FakeBucketStore()
    mine = [
        put(bucket, project_keys.file_key(organization_id, uuid4())),
        put(bucket, project_keys.file_key(organization_id, uuid4())),
        put(bucket, document_keys.document_key(organization_id, uuid4(), "manual.pdf")),
    ]

    result = await files.purge_files(bucket, organization_id)

    assert result == FilesPurged(removed=3, failed=0)
    assert sorted(bucket.deleted) == sorted(mine)
    assert bucket.objects == {}


async def test_it_leaves_every_other_organizations_files_alone():
    mine, other = uuid4(), uuid4()
    bucket = FakeBucketStore()
    put(bucket, project_keys.file_key(mine, uuid4()))
    theirs = put(bucket, project_keys.file_key(other, uuid4()))
    their_document = put(bucket, document_keys.document_key(other, uuid4(), "x.pdf"))
    shared_root = put(bucket, f"{settings.BUCKET_PREFIX}/downloads/desktop/THE-WAY-Setup.exe")

    await files.purge_files(bucket, mine)

    assert set(bucket.objects) == {theirs, their_document, shared_root}


async def test_it_never_deletes_a_key_outside_the_prefix_even_if_the_listing_returns_one():
    """A bucket that lists loosely (a prefix match that is not a path match) must not make the
    purge reach beyond the organization."""
    organization_id = uuid4()
    prefix = keys.organization_prefix(organization_id)

    class LooseListing(FakeBucketStore):
        async def list(self, prefix_asked: str = ""):
            listed = await super().list("")  # ignores the prefix it was given
            return listed

    bucket = LooseListing()
    inside = put(bucket, prefix + "files/a")
    outside = put(bucket, "somebody/elses/file")

    result = await files.purge_files(bucket, organization_id)

    assert result.removed == 1
    assert bucket.deleted == [inside]
    assert outside in bucket.objects


async def test_an_organization_with_no_files_is_a_clean_no_op():
    bucket = FakeBucketStore()

    assert await files.purge_files(bucket, uuid4()) == FilesPurged(removed=0, failed=0)
    assert bucket.deleted == []


async def test_a_file_that_cannot_be_deleted_is_counted_and_the_rest_still_go():
    organization_id = uuid4()
    bad = project_keys.file_key(organization_id, uuid4())

    class OneRefuses(FakeBucketStore):
        async def delete(self, key: str) -> None:
            if key == bad:
                raise BucketError("denied")
            await super().delete(key)

    bucket = OneRefuses()
    put(bucket, bad)
    good = [put(bucket, project_keys.file_key(organization_id, uuid4())) for _ in range(4)]

    result = await files.purge_files(bucket, organization_id)

    assert result == FilesPurged(removed=4, failed=1)
    assert set(bucket.deleted) == set(good)
    assert bad in bucket.objects


async def test_running_it_again_finishes_what_a_failure_left():
    organization_id = uuid4()
    stuck = project_keys.file_key(organization_id, uuid4())
    refuse = {"on": True}

    class Flaky(FakeBucketStore):
        async def delete(self, key: str) -> None:
            if key == stuck and refuse["on"]:
                raise BucketError("temporary")
            await super().delete(key)

    bucket = Flaky()
    put(bucket, stuck)
    put(bucket, project_keys.file_key(organization_id, uuid4()))

    first = await files.purge_files(bucket, organization_id)
    refuse["on"] = False
    second = await files.purge_files(bucket, organization_id)

    assert (first.removed, first.failed) == (1, 1)
    assert (second.removed, second.failed) == (1, 0)
    assert bucket.objects == {}


async def test_more_files_than_fit_in_one_batch_all_go():
    organization_id = uuid4()
    bucket = FakeBucketStore()
    for _ in range(files.DELETE_AT_ONCE * 2 + 3):
        put(bucket, project_keys.file_key(organization_id, uuid4()))

    result = await files.purge_files(bucket, organization_id)

    assert result == FilesPurged(removed=files.DELETE_AT_ONCE * 2 + 3, failed=0)
    assert bucket.objects == {}


async def test_a_bucket_that_cannot_be_listed_raises_rather_than_claiming_success():
    with pytest.raises(BucketError):
        await files.purge_files(BrokenBucketStore(), uuid4())
