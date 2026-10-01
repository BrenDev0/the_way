from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.api import dependencies as api_dependencies
from src.api_keys import dependencies as api_keys_dependencies
from src.api_keys.ports import ListApiKeysForUserFn
from src.auth import dependencies as auth_dependencies
from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ValidationError
from src.users.domain import User

from . import config
from . import use_cases as voice_use_cases
from .schemas import SpeechRequest, TranscriptionResponse

router = APIRouter(tags=["voice"])

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]
ListApiKeys = Annotated[
    ListApiKeysForUserFn,
    Depends(api_keys_dependencies.provide_list_api_keys_for_user_fn),
]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]


@router.post("/transcriptions", response_model=TranscriptionResponse)
async def transcribe_route(
    request: Request,
    current_user: CurrentUser,
    list_api_keys_for_user_fn: ListApiKeys,
    encryption_service: Encryption,
) -> TranscriptionResponse:
    """The body is the recording itself, as audio/wav -- one spoken turn, not a form."""
    # refused before reading, so an oversized upload is never held in memory
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > config.MAX_AUDIO_BYTES:
        raise ValidationError(message="That recording is too long", code="voice_audio_too_large")

    audio = await request.body()
    api_key = await voice_use_cases.openai_key(
        current_user.id, list_api_keys_for_user_fn, encryption_service
    )
    return TranscriptionResponse(text=await voice_use_cases.transcribe(audio, api_key))


@router.post("/speech")
async def speech_route(
    payload: SpeechRequest,
    current_user: CurrentUser,
    list_api_keys_for_user_fn: ListApiKeys,
    encryption_service: Encryption,
) -> StreamingResponse:
    """The text spoken, streamed back as raw 16-bit mono pcm at 24 kHz."""
    api_key = await voice_use_cases.openai_key(
        current_user.id, list_api_keys_for_user_fn, encryption_service
    )
    return StreamingResponse(
        await voice_use_cases.speak(payload.text, api_key),
        media_type="audio/pcm",
        headers={"X-Sample-Rate": str(config.PLAYBACK_RATE)},
    )
