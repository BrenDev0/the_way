import pytest
from helpers import FakeBucketStore

from src.core.exceptions import NotFoundError
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
