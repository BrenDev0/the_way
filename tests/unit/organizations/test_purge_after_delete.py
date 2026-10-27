"""Clearing a deleted organization's files from the bucket: after its rows are gone, and never
able to undo the deletion."""

import logging
from uuid import uuid4

from src.core.bucket.domain import BucketError
from src.organizations import use_cases
from src.organizations.domain import FilesPurged


async def test_the_organizations_files_are_cleared_and_counted():
    seen = []

    async def purge(organization_id):
        seen.append(organization_id)
        return FilesPurged(removed=7, failed=0)

    organization_id = uuid4()
    purged = await use_cases.purge_files_of_deleted_organization(organization_id, purge)

    assert purged == FilesPurged(removed=7, failed=0)
    assert seen == [organization_id]


async def test_a_bucket_that_cannot_be_reached_does_not_undo_or_fail_the_deletion(caplog):
    async def purge(_organization_id):
        raise BucketError("no route to bucket")

    with caplog.at_level(logging.WARNING):
        purged = await use_cases.purge_files_of_deleted_organization(uuid4(), purge)

    assert purged is None  # nobody can say what is left
    assert "Could not clear the files of deleted organization" in caplog.text


async def test_files_that_could_not_be_deleted_are_logged_by_count(caplog):
    async def purge(_organization_id):
        return FilesPurged(removed=3, failed=2)

    with caplog.at_level(logging.WARNING):
        purged = await use_cases.purge_files_of_deleted_organization(uuid4(), purge)

    assert purged == FilesPurged(removed=3, failed=2)
    assert "2 files of deleted organization" in caplog.text
