import pytest
from helpers import BrokenBucketStore, FakeBucketStore

from src.core.bucket.domain import BucketError
from src.core.exceptions import NotFoundError, ServiceUnavailableError
from src.downloads import config
from src.downloads.fastapi import routes


def published(*platforms: str) -> FakeBucketStore:
    bucket = FakeBucketStore(download_url="https://bucket.example/signed")
    for platform in platforms:
        bucket.objects[config.key(config.INSTALLERS[platform])] = 123_000_000
    # someone else's file beside them is not an installer
    bucket.objects[config.folder() + "notes.txt"] = 10
    return bucket


async def test_the_page_learns_which_installers_are_published():
    listed = {item.platform: item for item in await routes.list_installers(published("windows"))}

    assert listed["windows"].available and listed["windows"].size_bytes == 123_000_000
    assert not listed["mac"].available and listed["mac"].size_bytes is None
    assert set(listed) == {"windows", "mac"}


async def test_a_published_installer_gets_a_short_link_that_saves_under_its_name():
    bucket = published("mac")

    link = await routes.installer_link("mac", bucket)

    assert link.url == "https://bucket.example/signed"
    key, seconds, name = bucket.presigned_gets[0]
    assert key == config.key(config.INSTALLERS["mac"])
    assert seconds == config.LINK_SECONDS
    assert name == link.filename == "THE-WAY-mac.zip"


@pytest.mark.parametrize("platform", ["windows", "linux", "../projects"])
async def test_nothing_unpublished_or_unknown_is_handed_out(platform):
    bucket = published("mac")

    with pytest.raises(NotFoundError):
        await routes.installer_link(platform, bucket)
    assert bucket.presigned_gets == []


def test_installers_live_in_their_own_folder_under_the_prefix():
    for installer in config.INSTALLERS.values():
        assert config.key(installer).startswith(config.folder())
        assert "organizations" not in config.key(installer)


# --- a bucket that cannot be read: the page is told to try again, not given a 500 -----------


async def test_the_page_gets_a_503_not_a_500_when_the_bucket_cannot_be_read(caplog):
    with caplog.at_level("WARNING"), pytest.raises(ServiceUnavailableError) as raised:
        await routes.list_installers(BrokenBucketStore())

    assert raised.value.status_code == 503
    assert raised.value.code == "downloads_unavailable"
    assert "Las descargas no están disponibles" in raised.value.message
    # the reason is logged, so a misconfigured bucket is still seen
    assert "signature we calculated" in caplog.text


async def test_the_503_does_not_carry_the_buckets_reason_to_the_browser():
    with pytest.raises(ServiceUnavailableError) as raised:
        await routes.list_installers(BrokenBucketStore())

    assert "signature" not in raised.value.message.lower()


async def test_a_link_cannot_be_made_when_the_bucket_cannot_be_read():
    with pytest.raises(ServiceUnavailableError) as raised:
        await routes.installer_link("windows", BrokenBucketStore())

    assert raised.value.code == "downloads_unavailable"


async def test_a_link_cannot_be_made_when_only_signing_it_fails():
    class SigningFails(FakeBucketStore):
        async def presign_get(self, key, expires_in, download_name=None):
            raise BucketError("Failed preparing a download")

    bucket = SigningFails()
    bucket.objects[config.key(config.INSTALLERS["windows"])] = 1

    with pytest.raises(ServiceUnavailableError):
        await routes.installer_link("windows", bucket)


async def test_an_unknown_platform_is_still_a_404_even_with_a_broken_bucket():
    with pytest.raises(NotFoundError) as raised:
        await routes.installer_link("linux", BrokenBucketStore())

    assert raised.value.code == "installer_not_published"
