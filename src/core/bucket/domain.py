from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int
    modified: datetime | None = None


class BucketError(Exception):
    pass


class BucketObjectMissing(BucketError):
    """The bucket answered, and the object is not there -- unlike a bucket that cannot be
    reached, trying again will not bring it back."""
