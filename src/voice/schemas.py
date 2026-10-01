from pydantic import Field

from src.core.schemas import ApiBaseModel

from . import config


class TranscriptionResponse(ApiBaseModel):
    text: str


class SpeechRequest(ApiBaseModel):
    text: str = Field(min_length=1, max_length=config.MAX_SPEAK_CHARS)
