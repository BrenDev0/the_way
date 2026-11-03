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


# --- the version in the name the installer is saved as ----------------------------------------


@pytest.mark.parametrize(
    ("platform", "version", "name"),
    [
        ("windows", "0.1.7", "THE-WAY-Setup-0.1.7.exe"),
        ("mac", "1.20.3", "THE-WAY-mac-1.20.3.zip"),
        ("windows", None, "THE-WAY-Setup.exe"),
        # read from a file in the bucket: only a plain x.y.z goes into a file name
        ("windows", "0.1.7/../../x", "THE-WAY-Setup.exe"),
        ("windows", "0.1.7-beta", "THE-WAY-Setup.exe"),
        ("windows", "", "THE-WAY-Setup.exe"),
    ],
)
def test_the_name_it_is_saved_as_carries_the_version_when_it_is_known(platform, version, name):
    assert config.download_name(config.INSTALLERS[platform], version) == name


async def test_the_link_saves_the_installer_under_a_name_with_its_version():
    bucket = bucket_with(windows="0.1.7")

    link = await routes.installer_link("windows", bucket)

    assert link.filename == "THE-WAY-Setup-0.1.7.exe"
    key, _, name = bucket.presigned_gets[0]
    # published before versions went in the key: the file at the fixed name is still served
    assert key == config.key(config.INSTALLERS["windows"])
    assert name == "THE-WAY-Setup-0.1.7.exe"


async def test_the_page_lists_the_installer_under_its_versioned_name():
    listed = {item.platform: item for item in await routes.list_installers(bucket_with(windows="0.1.7"))}

    assert listed["windows"].filename == "THE-WAY-Setup-0.1.7.exe"
    assert listed["mac"].filename == "THE-WAY-mac.zip"  # nothing published, no version to name


# --- the desktop app updating itself -------------------------------------------------------------


async def test_the_app_is_given_a_link_to_the_installer_with_its_version():
    bucket = bucket_with(windows="0.1.7")

    answer = await desktop_routes.app_installer("windows", bucket)

    assert answer.version == "0.1.7"
    assert answer.filename == "THE-WAY-Setup-0.1.7.exe"
    assert answer.url == "https://bucket.example/download"


async def test_the_app_is_told_when_there_is_nothing_to_download():
    from src.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError) as raised:
        await desktop_routes.app_installer("windows", FakeBucketStore())

    assert raised.value.code == "installer_not_published"


async def test_the_app_gets_a_503_not_a_500_when_the_bucket_cannot_be_read():
    from src.core.exceptions import ServiceUnavailableError

    with pytest.raises(ServiceUnavailableError) as raised:
        await desktop_routes.app_installer("windows", BrokenBucketStore())

    assert raised.value.code == "downloads_unavailable"


# --- the version in the key it is stored under ------------------------------------------------


def stored_with_version(version: str, platform: str = "windows", *, also_fixed: bool = False) -> FakeBucketStore:
    """A bucket whose installer sits under its versioned name, as a publish now leaves it."""
    installer = config.INSTALLERS[platform]
    bucket = FakeBucketStore()
    bucket.objects[config.versioned_key(installer, version)] = 123
    if also_fixed:
        bucket.objects[config.key(installer)] = 99
    body = json.dumps({"version": version}).encode()
    bucket.objects[config.version_key(installer)] = len(body)
    bucket.contents[config.version_key(installer)] = body
    return bucket


def test_a_version_is_stored_under_the_name_it_is_saved_as():
    installer = config.INSTALLERS["windows"]
    key = config.versioned_key(installer, "0.1.11")

    assert key is not None and key.endswith("/windows/THE-WAY-Setup-0.1.11.exe")
    assert key.startswith(config.folder())
    assert key.rsplit("/", 1)[1] == config.download_name(installer, "0.1.11")


@pytest.mark.parametrize("version", [None, "", "latest", "0.1.7/../../x", "0.1.7-beta"])
def test_only_a_plain_version_makes_a_key(version):
    assert config.versioned_key(config.INSTALLERS["windows"], version) is None


async def test_the_link_goes_to_the_file_stored_with_its_version():
    bucket = stored_with_version("0.1.11")

    link = await routes.installer_link("windows", bucket)

    key, _, name = bucket.presigned_gets[0]
    assert key.endswith("/windows/THE-WAY-Setup-0.1.11.exe")
    assert name == link.filename == "THE-WAY-Setup-0.1.11.exe"


async def test_the_versioned_file_wins_over_one_left_at_the_old_fixed_name():
    bucket = stored_with_version("0.1.11", also_fixed=True)

    await routes.installer_link("windows", bucket)

    assert bucket.presigned_gets[0][0].endswith("THE-WAY-Setup-0.1.11.exe")


async def test_a_version_recorded_without_its_file_is_not_handed_out():
    from src.core.exceptions import NotFoundError

    bucket = stored_with_version("0.1.11")
    del bucket.objects[config.versioned_key(config.INSTALLERS["windows"], "0.1.11")]

    with pytest.raises(NotFoundError):
        await routes.installer_link("windows", bucket)


async def test_the_page_and_the_app_see_the_size_of_the_versioned_file():
    bucket = stored_with_version("0.1.11", also_fixed=True)

    listed = {item.platform: item for item in await routes.list_installers(bucket)}
    answer = await desktop_routes.app_installer("windows", bucket)

    assert listed["windows"].available and listed["windows"].size_bytes == 123
    assert listed["windows"].filename == "THE-WAY-Setup-0.1.11.exe"
    assert answer.filename == "THE-WAY-Setup-0.1.11.exe" and answer.version == "0.1.11"


def keys_for(*names: str) -> list[str]:
    installer = config.INSTALLERS["windows"]
    return [config.platform_folder(installer) + name for name in names]


def test_a_publish_keeps_the_newest_versions_and_removes_the_rest():
    installer = config.INSTALLERS["windows"]
    held = keys_for(
        "THE-WAY-Setup-0.1.7.exe", "THE-WAY-Setup-0.1.8.exe", "THE-WAY-Setup-0.1.9.exe",
        "THE-WAY-Setup-0.1.10.exe", "THE-WAY-Setup-0.1.11.exe", "latest.json", "notes.txt",
    )

    removed = config.superseded(installer, held, current="0.1.11")

    # numerically, not alphabetically: 0.1.10 is newer than 0.1.9
    assert removed == keys_for("THE-WAY-Setup-0.1.7.exe", "THE-WAY-Setup-0.1.8.exe")


def test_a_publish_removes_the_file_at_the_old_fixed_name():
    installer = config.INSTALLERS["windows"]
    held = keys_for("THE-WAY-Setup.exe", "THE-WAY-Setup-0.1.11.exe", "latest.json")

    assert config.superseded(installer, held, current="0.1.11") == keys_for("THE-WAY-Setup.exe")


def test_what_is_announced_is_never_removed_even_when_older_than_what_is_kept():
    installer = config.INSTALLERS["windows"]
    held = keys_for(
        "THE-WAY-Setup-0.1.5.exe", "THE-WAY-Setup-0.1.9.exe", "THE-WAY-Setup-0.1.10.exe",
        "THE-WAY-Setup-0.1.11.exe",
    )

    removed = config.superseded(installer, held, current="0.1.5")

    assert keys_for("THE-WAY-Setup-0.1.5.exe")[0] not in removed
    assert removed == []  # the three newest and the one announced: nothing else is held


def test_nothing_that_is_not_an_installer_of_that_platform_is_removed():
    installer = config.INSTALLERS["windows"]
    held = keys_for("latest.json", "notes.txt", "THE-WAY-mac-0.1.1.zip", "THE-WAY-Setup-0.1.x.exe")

    assert config.superseded(installer, held, current="0.1.11") == []


async def test_publishing_stores_the_version_in_the_key_then_clears_the_old(tmp_path, monkeypatch):
    from src.core.bucket.boto3 import adapter
    from src.core.settings.shared import settings

    installer = config.INSTALLERS["windows"]
    bucket = FakeBucketStore()
    for name in ("THE-WAY-Setup.exe", "THE-WAY-Setup-0.1.8.exe", "THE-WAY-Setup-0.1.9.exe", "THE-WAY-Setup-0.1.10.exe"):
        bucket.objects[config.platform_folder(installer) + name] = 1
    monkeypatch.setattr(adapter, "Boto3BucketStore", lambda **_: bucket)
    monkeypatch.setattr(settings, "BUCKET_NAME", "test-bucket")
    source = tmp_path / "THE-WAY-Setup.exe"
    source.write_bytes(b"installer")

    message = await publish.publish("windows", source, "0.1.11")

    assert config.versioned_key(installer, "0.1.11") in bucket.objects
    assert json.loads(bucket.contents[config.version_key(installer)])["version"] == "0.1.11"
    assert config.key(installer) not in bucket.objects  # the old fixed name is gone
    assert config.platform_folder(installer) + "THE-WAY-Setup-0.1.8.exe" not in bucket.objects
    assert "2 older removed" in message
