import json

import pytest
from helpers import FakeBucketStore

from src.core.settings import settings
from src.downloads import config, desktop_routes, publish, routes, versions


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
    monkeypatch.setattr(settings, "DESKTOP_DOWNLOAD_PAGE_URL", None)
    monkeypatch.setattr(settings, "INVITATION_ACCEPT_URL", "https://panel.example.com/accept-invite")
    assert config.download_page_url() == "https://panel.example.com/download"

    monkeypatch.setattr(settings, "DESKTOP_DOWNLOAD_PAGE_URL", "https://theway.example/descargas")
    assert config.download_page_url() == "https://theway.example/descargas"


def test_publishing_needs_a_real_version_number(tmp_path, capsys):
    installer = tmp_path / "THE-WAY-Setup.exe"
    installer.write_bytes(b"x")

    with pytest.raises(SystemExit):
        publish.main(["windows", str(installer)])  # no --version
    assert publish.main(["windows", str(installer), "--version", "latest"]) == 1
    assert "Not a version" in capsys.readouterr().err
