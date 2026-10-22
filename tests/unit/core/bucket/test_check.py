"""The bucket diagnostic (python -m src.core.bucket.check): what it says about a service's
bucket settings, and that it never prints a secret."""

import pytest

from src.core.bucket import check
from src.core.bucket.domain import BucketError

SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
KEY_ID = "AKIAIOSFODNN7EXAMPLE"


def good(**overrides) -> dict[str, str | None]:
    values: dict[str, str | None] = {
        "BUCKET_NAME": "the-way",
        "BUCKET_PREFIX": "the_way",
        "BUCKET_ENDPOINT": "https://storage.example.com",
        "BUCKET_PUBLIC_ENDPOINT": None,
        "BUCKET_REGION": "us-east-1",
        "BUCKET_ACCESS_KEY_ID": KEY_ID,
        "BUCKET_SECRET_ACCESS_KEY": SECRET,
    }
    values.update(overrides)
    return values


# --- what is printed about a value ----------------------------------------------------------


def test_a_secret_is_shown_only_by_its_length_and_two_characters():
    line = check.shape("BUCKET_SECRET_ACCESS_KEY", SECRET)

    assert str(len(SECRET)) in line
    assert SECRET not in line
    assert SECRET[:3] not in line  # not even three characters of it
    assert SECRET[:2] in line


def test_the_key_id_is_treated_as_a_secret_too():
    assert KEY_ID not in check.shape("BUCKET_ACCESS_KEY_ID", KEY_ID)


def test_other_values_are_shown_as_they_are_so_stray_spaces_and_quotes_can_be_seen():
    assert check.shape("BUCKET_REGION", " us-east-1 ") == repr(" us-east-1 ")
    assert check.shape("BUCKET_ENDPOINT", '"https://x.example"') == repr('"https://x.example"')


def test_unset_and_empty_are_told_apart():
    assert check.shape("BUCKET_REGION", None) == "not set"
    assert check.shape("BUCKET_REGION", "") == "set, but empty"


# --- what is wrong with the values themselves -----------------------------------------------


def test_a_correct_configuration_has_no_problems():
    assert check.problems(good()) == []


def test_a_correct_configuration_with_a_public_endpoint_has_no_problems():
    assert check.problems(good(BUCKET_PUBLIC_ENDPOINT="https://public.example.com/")) == []


@pytest.mark.parametrize("name", ["BUCKET_SECRET_ACCESS_KEY", "BUCKET_ACCESS_KEY_ID", "BUCKET_REGION"])
@pytest.mark.parametrize("bad", [" padded", "padded ", "padded\n"])
def test_a_space_or_line_break_at_either_end_is_found(name, bad):
    problems = check.problems(good(**{name: bad}))

    assert any(name in problem and "space or a line break" in problem for problem in problems)


def test_a_space_around_the_endpoint_is_found():
    problems = check.problems(good(BUCKET_ENDPOINT=" https://storage.example.com"))

    assert any("BUCKET_ENDPOINT" in p and "space or a line break" in p for p in problems)


@pytest.mark.parametrize("quoted", ['"abc"', "'abc'", '"abc', "abc'"])
def test_a_value_wrapped_in_quotes_is_found(quoted):
    problems = check.problems(good(BUCKET_SECRET_ACCESS_KEY=quoted))

    assert any("BUCKET_SECRET_ACCESS_KEY" in p and "quotes" in p for p in problems)


def test_no_bucket_name_means_no_file_store_at_all():
    problems = check.problems(good(BUCKET_NAME=None))

    assert any("BUCKET_NAME is not set" in p for p in problems)
    # and it does not pile on about credentials for a store that is off
    assert not any("ACCESS" in p and "is not set" in p for p in problems)


@pytest.mark.parametrize("name", ["BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"])
def test_a_named_bucket_without_its_key_pair_is_found(name):
    problems = check.problems(good(**{name: None}))

    assert any(f"{name} is not set" in p for p in problems)


@pytest.mark.parametrize(
    ("endpoint", "fragment"),
    [
        ("storage.example.com", "full address"),
        ("ftp://storage.example.com", "full address"),
        ("https://storage.example.com/the-way", "path after the host"),
        ("https://storage.example.com/the-way/", "path after the host"),
    ],
)
def test_an_endpoint_that_is_not_just_a_host_is_found(endpoint, fragment):
    problems = check.problems(good(BUCKET_ENDPOINT=endpoint))

    assert any("BUCKET_ENDPOINT" in p and fragment in p for p in problems)


def test_a_trailing_slash_on_the_host_alone_is_fine():
    assert check.problems(good(BUCKET_ENDPOINT="https://storage.example.com/")) == []


def test_an_endpoint_without_a_region_is_found():
    problems = check.problems(good(BUCKET_REGION=None))

    assert any("BUCKET_ENDPOINT is set but BUCKET_REGION is not" in p for p in problems)


def test_no_endpoint_means_no_region_complaint():
    """Real S3 is reached by region alone: an endpoint is only needed for other providers."""
    assert check.problems(good(BUCKET_ENDPOINT=None, BUCKET_REGION=None)) == []


# --- what to look at next -------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "Failed listing x/: The request signature we calculated does not match the signature you provided.",
        "Failed listing x/: An error occurred (InvalidAccessKeyId) when calling the ListObjectsV2 operation",
        "Failed listing x/: Access Denied.",
    ],
)
def test_a_refused_signature_points_at_the_key_pair_the_region_and_the_endpoint(reason):
    said = check.hint(reason)

    assert "key pair" in said and "BUCKET_REGION" in said and "BUCKET_ENDPOINT" in said


def test_a_missing_bucket_points_at_its_name_not_the_credentials():
    said = check.hint("Failed listing x/: The specified bucket does not exist")

    assert "BUCKET_NAME" in said and "key pair" not in said


def test_anything_else_points_at_the_endpoint_and_the_name_not_the_credentials():
    said = check.hint("Failed listing x/: The specified key does not exist.")

    assert "BUCKET_ENDPOINT" in said and "key pair" not in said


# --- the command itself ---------------------------------------------------------------------


class StubStore:
    """Stands in for the real adapter: records how it was built, and either answers or fails."""

    outcome: list | BucketError = []
    built: dict = {}
    listed: list[str] = []
    closed = False

    def __init__(self, **kwargs):
        type(self).built = kwargs

    async def list(self, prefix: str = ""):
        type(self).listed.append(prefix)
        if isinstance(self.outcome, BucketError):
            raise self.outcome
        return self.outcome

    async def aclose(self):
        type(self).closed = True


@pytest.fixture
def configured(monkeypatch):
    from src.core.bucket.boto3 import adapter
    from src.core.settings.shared import settings

    for name, value in good().items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(adapter, "Boto3BucketStore", StubStore)
    StubStore.listed = []
    StubStore.closed = False
    StubStore.outcome = []
    return settings


async def test_when_the_bucket_answers_it_says_so_and_exits_cleanly(configured, capsys):
    assert await check.main() == 0

    out = capsys.readouterr().out
    assert "OK: the bucket answered" in out
    assert StubStore.listed == [check.PROBE_PREFIX]  # one read-only listing, of nothing real
    assert StubStore.closed


async def test_the_store_is_built_from_what_the_service_has(configured):
    await check.main()

    assert StubStore.built["bucket"] == "the-way"
    assert StubStore.built["region"] == "us-east-1"
    assert StubStore.built["endpoint_url"] == "https://storage.example.com"
    assert StubStore.built["access_key"] == KEY_ID
    assert StubStore.built["secret_key"] == SECRET


async def test_when_the_bucket_refuses_it_prints_the_reason_and_exits_with_1(configured, capsys):
    StubStore.outcome = BucketError(
        "Failed listing: An error occurred (SignatureDoesNotMatch) when calling the ListObjectsV2 operation"
    )

    assert await check.main() == 1

    out = capsys.readouterr().out
    assert "FAILED:" in out and "SignatureDoesNotMatch" in out
    assert "BUCKET_REGION" in out  # tells what to check next
    assert StubStore.closed


async def test_a_secret_is_never_printed_in_any_outcome(configured, capsys):
    await check.main()
    StubStore.outcome = BucketError("Failed listing: denied")
    await check.main()

    out = capsys.readouterr().out
    assert SECRET not in out
    assert KEY_ID not in out


async def test_a_value_problem_is_shown_and_fails_the_run_even_when_the_bucket_answers(configured, capsys, monkeypatch):
    monkeypatch.setattr(configured, "BUCKET_SECRET_ACCESS_KEY", SECRET + " ")

    assert await check.main() == 1

    assert "space or a line break" in capsys.readouterr().out


async def test_with_no_bucket_configured_it_stops_before_calling_anything(configured, capsys, monkeypatch):
    monkeypatch.setattr(configured, "BUCKET_NAME", None)

    assert await check.main() == 1

    assert StubStore.listed == []
    assert "BUCKET_NAME is not set" in capsys.readouterr().out
