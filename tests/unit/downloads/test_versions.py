import json

import pytest
from helpers import BrokenBucketStore, FakeBucketStore

from src.core.settings.api import settings as api_settings
from src.downloads import config, publish, versions
from src.downloads.fastapi import desktop_routes, routes


@pytest.fixture(autouse=True)
def fresh_cache():
    versions.forget()
    yield
    versions.forget()


def bucket_with(**recorded: str) -> FakeBucketStore:
    bucket = FakeBucketStore()
    for platform, version in recorded.items():
        installer = config.INSTALLERS[platform]
        bucket.objects[config.key(installer)] = 100
        body = json.dumps({"version": version}).encode()
        bucket.objects[config.version_key(installer)] = len(body)
        bucket.contents[config.version_key(installer)] = body
    return bucket


async def test_the_app_learns_the_latest_version_of_each_installer():
    answer = await desktop_routes.app_version(bucket_with(windows="0.1.1"))

    assert answer.latest == {"windows": "0.1.1", "mac": None}


async def test_an_installer_published_without_a_version_reports_none():
    bucket = FakeBucketStore()
    bucket.objects[config.key(config.INSTALLERS["mac"])] = 100

    assert (await versions.published(bucket))["mac"] is None


async def test_the_download_page_shows_the_version_too():
    listed = {item.platform: item for item in await routes.list_installers(bucket_with(mac="0.2.0"))}

    assert listed["mac"].version == "0.2.0"
    assert listed["windows"].version is None


async def test_the_bucket_is_not_read_on_every_ask():
    bucket = bucket_with(windows="0.1.1")
    await versions.published(bucket)
    bucket.contents[config.version_key(config.INSTALLERS["windows"])] = b'{"version": "9.9.9"}'

    assert (await versions.published(bucket))["windows"] == "0.1.1"  # cached
    versions.forget()
    assert (await versions.published(bucket))["windows"] == "9.9.9"


def test_the_download_page_is_found_beside_the_invitation_link(monkeypatch):
    monkeypatch.setattr(api_settings, "DESKTOP_DOWNLOAD_PAGE_URL", None)
    monkeypatch.setattr(api_settings, "INVITATION_ACCEPT_URL", "https://panel.example.com/accept-invite")
    assert config.download_page_url() == "https://panel.example.com/download"

    monkeypatch.setattr(api_settings, "DESKTOP_DOWNLOAD_PAGE_URL", "https://theway.example/descargas")
    assert config.download_page_url() == "https://theway.example/descargas"


def test_publishing_needs_a_real_version_number(tmp_path, capsys):
    installer = tmp_path / "THE-WAY-Setup.exe"
    installer.write_bytes(b"x")

    with pytest.raises(SystemExit):
        publish.main(["windows", str(installer)])  # no --version
    assert publish.main(["windows", str(installer), "--version", "latest"]) == 1
    assert "Not a version" in capsys.readouterr().err


# --- the app's start-up check must survive a bucket that cannot be read -------------------


async def test_the_app_is_told_nothing_is_known_when_the_bucket_cannot_be_read(caplog):
    """This is the call the desktop app makes as it starts. A bucket that refuses the request
    (wrong credentials, wrong region) used to turn it into a 500; the app only wants to know
    whether a newer version is out, and 'nothing known' is a valid answer."""
    with caplog.at_level("WARNING"):
        answer = await desktop_routes.app_version(BrokenBucketStore())

    assert answer.latest == {"windows": None, "mac": None}
    assert answer.download_page_url == config.download_page_url()
    assert "Could not read the published app versions" in caplog.text
    assert "signature we calculated" in caplog.text  # the reason is logged, not swallowed


async def test_every_platform_is_named_in_the_unknown_answer():
    answer = await desktop_routes.app_version(BrokenBucketStore())

    assert set(answer.latest) == set(config.INSTALLERS)


async def test_a_failed_read_is_not_remembered_so_the_next_ask_tries_again():
    await desktop_routes.app_version(BrokenBucketStore())

    # the bucket is fixed: the very next ask sees it, with no wait for a cache to expire
    answer = await desktop_routes.app_version(bucket_with(windows="0.1.1"))

    assert answer.latest["windows"] == "0.1.1"


async def test_a_healthy_bucket_still_answers_as_before():
    answer = await desktop_routes.app_version(bucket_with(windows="0.1.1", mac="0.1.0"))

    assert answer.latest == {"windows": "0.1.1", "mac": "0.1.0"}
