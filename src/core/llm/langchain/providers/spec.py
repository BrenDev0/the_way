from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    accepts_temperature: bool = False
