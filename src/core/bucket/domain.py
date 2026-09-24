from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int
    modified: datetime | None = None


class BucketError(Exception):
    pass
