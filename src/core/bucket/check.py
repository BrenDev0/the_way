"""What this service has configured for the bucket, and whether it can use it.

    python -m src.core.bucket.check

Run it where the problem is (on Railway: `railway ssh --service <api> -- python -m
src.core.bucket.check`). It prints the SHAPE of each BUCKET_* value -- length, stray spaces,
quotes, a path after the host -- and never a secret, then makes one read-only call: a listing
of a prefix that does not exist, which is the call that fails first when the credentials or the
region are wrong. Exit status 0 when the bucket answered, 1 when it did not.
"""

import asyncio
import sys
from urllib.parse import urlparse

# Nothing lives under this prefix: the listing comes back empty when the bucket works, and
# nothing is read, written or deleted either way.
PROBE_PREFIX = "__the_way_bucket_check__/"

SECRETS = {"BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"}


def shape(name: str, value: str | None) -> str:
    """One line about a variable, with nothing in it that is secret."""
    if value is None:
        return "not set"
    if value == "":
        return "set, but empty"
    if name in SECRETS:
        return f"set, {len(value)} characters, starts {value[:2]}..."
    return repr(value)


def problems(values: dict[str, str | None]) -> list[str]:
    """What is wrong with the values themselves, before anything is sent anywhere."""
    found = []
    for name, value in values.items():
        if not value:
            continue
        if value != value.strip():
            found.append(f"{name} has a space or a line break at its start or end")
        if value[0] in "\"'" or value[-1] in "\"'":
            found.append(f"{name} is wrapped in quotes, which become part of the value on Railway")

    if not values.get("BUCKET_NAME"):
        found.append("BUCKET_NAME is not set: the app runs with no file store at all")
    else:
        for name in ("BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"):
            if not values.get(name):
                found.append(f"{name} is not set")

    for name in ("BUCKET_ENDPOINT", "BUCKET_PUBLIC_ENDPOINT"):
        endpoint = (values.get(name) or "").strip()
        if not endpoint:
            continue
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            found.append(f"{name} is not a full address (it needs https://host)")
        elif parsed.path not in ("", "/"):
            found.append(f"{name} has a path after the host ({parsed.path!r}): the endpoint is the host alone")

    if values.get("BUCKET_ENDPOINT") and not values.get("BUCKET_REGION"):
        found.append(
            "BUCKET_ENDPOINT is set but BUCKET_REGION is not: requests are signed for a region, "
            "and it has to be the one the provider expects"
        )
    return found


def hint(reason: str) -> str:
    """What to look at next, from what the bucket said."""
    said = reason.lower()
    if "signature" in said or "access key" in said or "accesskey" in said or "access denied" in said:
        return (
            "The bucket does not accept this key pair as signed: it is not the one the bucket\n"
            "issued, it was rotated, or it carries a stray character. Check BUCKET_REGION and\n"
            "BUCKET_ENDPOINT next: the signature is made for them. Comparing the values with a\n"
            "service that works is the quickest way to see which."
        )
    if "bucket" in said and ("not exist" in said or "nosuchbucket" in said):
        return "There is no bucket with this name at this endpoint: check BUCKET_NAME and BUCKET_ENDPOINT."
    return (
        "Check BUCKET_ENDPOINT (the host alone, https://host) and BUCKET_NAME, and compare the\n"
        "values with a service that works."
    )


NAMES = (
    "BUCKET_NAME",
    "BUCKET_PREFIX",
    "BUCKET_ENDPOINT",
    "BUCKET_PUBLIC_ENDPOINT",
    "BUCKET_REGION",
    "BUCKET_ACCESS_KEY_ID",
    "BUCKET_SECRET_ACCESS_KEY",
)


async def main() -> int:
    from src.core.bucket.boto3.adapter import Boto3BucketStore
    from src.core.bucket.domain import BucketError
    from src.core.settings.shared import settings

    values: dict[str, str | None] = {name: getattr(settings, name) for name in NAMES}

    print("What this service has:")
    for name, value in values.items():
        print(f"  {name:<26} {shape(name, value)}")

    issues = problems(values)
    for issue in issues:
        print(f"\n! {issue}")

    if not values["BUCKET_NAME"]:
        return 1

    print("\nListing a prefix that does not exist (read only) ...")
    store = Boto3BucketStore(
        bucket=values["BUCKET_NAME"] or "",
        region=values["BUCKET_REGION"],
        access_key=values["BUCKET_ACCESS_KEY_ID"],
        secret_key=values["BUCKET_SECRET_ACCESS_KEY"],
        endpoint_url=values["BUCKET_ENDPOINT"],
        public_endpoint_url=values["BUCKET_PUBLIC_ENDPOINT"],
    )
    try:
        found = await store.list(PROBE_PREFIX)
    except BucketError as error:
        print(f"FAILED: {error}")
        print(f"\n{hint(str(error))}")
        return 1
    finally:
        await store.aclose()

    print(f"OK: the bucket answered ({len(found)} objects under the probe prefix, as expected).")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
