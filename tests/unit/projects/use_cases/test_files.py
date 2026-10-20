
import pytest
from helpers import FakeBucketStore

from src.core.bucket.domain import BucketError
from src.core.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from src.projects import config, keys, links
from src.projects.domain import FileStatus
from src.projects.use_cases import files as file_use_cases


async def test_an_upload_starts_pending_with_a_presigned_url(store, bucket, new_project, upload):
    project = await new_project()

    project_file = await upload(project, complete=False)

    assert project_file.status is FileStatus.PENDING
    assert bucket.presigned[0][0] == keys.file_key(project.organization_id, project_file.id)
    assert bucket.presigned[0][2] == config.UPLOAD_URL_TTL_SECONDS


async def test_the_bucket_key_depends_only_on_the_file_id(new_project, new_folder, upload):
    project = await new_project()
    folder = await new_folder(project)

    project_file = await upload(project, "logo.png", folder_id=folder.id, complete=False)

    key = keys.file_key(project.organization_id, project_file.id)
    assert "logo" not in key
    assert str(folder.id) not in key


async def test_completing_records_the_size_the_bucket_actually_holds(
    store, bucket, new_project, upload
):
    project = await new_project()
    pending = await upload(project, size_bytes=10, complete=False)
    bucket.objects[keys.file_key(project.organization_id, pending.id)] = 4096

    ready = await file_use_cases.complete_upload(
        project=project,
        file_id=pending.id,
        get_file_fn=store.get_file,
        update_file_fn=store.update_file,
        bucket_store=bucket,
    )

    assert ready.status is FileStatus.READY
    assert ready.size_bytes == 4096


async def test_completing_before_the_upload_is_a_conflict(store, bucket, new_project, upload):
    project = await new_project()
    pending = await upload(project, complete=False)

    with pytest.raises(ConflictError) as exc:
        await file_use_cases.complete_upload(
            project=project,
            file_id=pending.id,
            get_file_fn=store.get_file,
            update_file_fn=store.update_file,
            bucket_store=bucket,
        )

    assert exc.value.code == "file_not_uploaded"


async def test_a_file_larger_than_s3_allows_is_refused(new_project, upload):
    project = await new_project()

    with pytest.raises(ValidationError) as exc:
        await upload(project, size_bytes=config.MAX_FILE_BYTES + 1, complete=False)

    assert exc.value.code == "file_too_large"


async def test_an_empty_file_can_be_uploaded(new_project, upload):
    project = await new_project()

    assert (await upload(project, "empty.txt", size_bytes=0)).size_bytes == 0


async def test_uploading_over_a_finished_file_is_a_conflict(new_project, upload):
    project = await new_project()
    await upload(project, "logo.png")

    with pytest.raises(ConflictError) as exc:
        await upload(project, "LOGO.png")

    assert exc.value.code == "project_entry_name_taken"


async def test_uploading_over_an_abandoned_upload_replaces_it(
    store, bucket, new_project, upload
):
    project = await new_project()
    abandoned = await upload(project, "logo.png", complete=False)

    fresh = await upload(project, "logo.png", complete=False)

    assert list(store.files) == [fresh.id]
    assert keys.file_key(project.organization_id, abandoned.id) in bucket.deleted


async def test_a_download_url_names_the_file(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project, "logo.png")

    _file, url = await file_use_cases.request_download(
        project=project, file_id=ready.id, get_file_fn=store.get_file, bucket_store=bucket
    )

    assert url == bucket.download_url
    assert bucket.presigned_gets == [
        (
            keys.file_key(project.organization_id, ready.id),
            config.DOWNLOAD_URL_TTL_SECONDS,
            "logo.png",
        )
    ]


async def test_a_pending_file_cannot_be_downloaded(store, bucket, new_project, upload):
    project = await new_project()
    pending = await upload(project, complete=False)

    with pytest.raises(ConflictError):
        await file_use_cases.request_download(
            project=project, file_id=pending.id, get_file_fn=store.get_file, bucket_store=bucket
        )


async def test_a_file_from_another_project_is_not_found(store, bucket, new_project, upload):
    project = await new_project("One")
    other = await new_project("Two")
    foreign = await upload(other)

    with pytest.raises(NotFoundError) as exc:
        await file_use_cases.request_download(
            project=project, file_id=foreign.id, get_file_fn=store.get_file, bucket_store=bucket
        )

    assert exc.value.code == "file_not_found"


async def test_renaming_a_file_leaves_the_bucket_alone(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project, "draft.txt")

    renamed = await file_use_cases.rename_file(
        project=project,
        file_id=ready.id,
        name="final.txt",
        get_file_fn=store.get_file,
        find_entry_fn=store.find_entry,
        update_file_fn=store.update_file,
    )

    assert renamed.name == "final.txt"
    assert bucket.deleted == []


async def test_a_file_moves_into_a_folder_and_back(store, new_project, new_folder, upload):
    project = await new_project()
    folder = await new_folder(project)
    ready = await upload(project)

    async def move(folder_id):
        return await file_use_cases.move_file(
            project=project,
            file_id=ready.id,
            folder_id=folder_id,
            get_file_fn=store.get_file,
            get_folder_fn=store.get_folder,
            find_entry_fn=store.find_entry,
            update_file_fn=store.update_file,
        )

    assert (await move(folder.id)).folder_id == folder.id
    assert (await move(None)).folder_id is None


async def test_deleting_a_file_removes_its_object(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project)

    await file_use_cases.delete_file(
        project=project,
        file_id=ready.id,
        get_file_fn=store.get_file,
        delete_file_fn=store.delete_file,
        bucket_store=bucket,
    )

    assert store.files == {}
    assert bucket.deleted == [keys.file_key(project.organization_id, ready.id)]


# --- an image by its signed link ---------------------------------------------


async def test_a_signed_link_gives_a_fresh_bucket_url_for_the_image(store, bucket, new_project, upload):
    project = await new_project()
    image = await upload(project)

    url = await file_use_cases.request_image_url(
        image.id, links.sign(image.id), store.get_file_with_project, bucket
    )

    assert url == bucket.download_url
    assert bucket.presigned_gets == [
        (keys.file_key(project.organization_id, image.id), config.IMAGE_URL_TTL_SECONDS, None)
    ]


async def test_a_wrong_signature_is_a_not_found_not_a_forbidden(store, bucket, new_project, upload):
    image = await upload(await new_project())

    with pytest.raises(NotFoundError) as exc:
        await file_use_cases.request_image_url(image.id, "0" * 32, store.get_file_with_project, bucket)

    assert exc.value.code == "image_not_found"
    assert bucket.presigned_gets == []


async def test_a_file_that_does_not_exist_is_the_same_not_found(store, bucket):
    from uuid import uuid4

    missing = uuid4()

    with pytest.raises(NotFoundError) as exc:
        await file_use_cases.request_image_url(
            missing, links.sign(missing), store.get_file_with_project, bucket
        )

    assert exc.value.code == "image_not_found"


async def test_a_file_still_uploading_is_not_served(store, bucket, new_project, upload):
    pending = await upload(await new_project(), complete=False)

    with pytest.raises(NotFoundError):
        await file_use_cases.request_image_url(
            pending.id, links.sign(pending.id), store.get_file_with_project, bucket
        )


async def test_only_images_are_served_this_way(store, bucket, new_project, upload):
    document = await upload(await new_project(), name="plan.pdf")
    store.files[document.id].content_type = "application/pdf"

    with pytest.raises(NotFoundError):
        await file_use_cases.request_image_url(
            document.id, links.sign(document.id), store.get_file_with_project, bucket
        )


async def test_an_unavailable_bucket_is_a_service_error_not_a_not_found(store, new_project, upload, bucket):
    image = await upload(await new_project())

    class DownBucket(FakeBucketStore):
        async def presign_get(self, key, expires_in, download_name=None):
            raise BucketError("down")

    with pytest.raises(ServiceUnavailableError) as exc:
        await file_use_cases.request_image_url(
            image.id, links.sign(image.id), store.get_file_with_project, DownBucket()
        )

    assert exc.value.code == "image_unavailable"
