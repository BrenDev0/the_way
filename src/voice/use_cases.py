import io
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from uuid import UUID

import openai
from openai import AsyncOpenAI

from src.api_keys.domain import Provider
from src.api_keys.ports import ListApiKeysForUserFn
from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ConflictError, ServiceUnavailableError, ValidationError

from . import config


async def openai_key(
    user_id: UUID,
    list_api_keys_for_user_fn: ListApiKeysForUserFn,
    encryption_service: EncryptionService,
) -> str:
    """Voice runs on OpenAI whichever provider the chat itself uses, so it needs the
    user's own OpenAI key -- there is no server-wide one to fall back on."""
    for key in await list_api_keys_for_user_fn(user_id):
        if key.provider is Provider.OPENAI:
            return encryption_service.decrypt(key.encrypted_secret)

    raise ConflictError(
        message=(
            "Voice needs an OpenAI key. "
            "Ask an owner or admin in your organization to issue you one."
        ),
        code="voice_key_not_configured",
    )


async def transcribe(audio: bytes, api_key: str) -> str:
    if len(audio) > config.MAX_AUDIO_BYTES:
        raise ValidationError(message="That recording is too long", code="voice_audio_too_large")

    if len(audio) < config.MIN_AUDIO_BYTES:
        return ""

    buffer = io.BytesIO(audio)
    # the API picks its decoder off the filename, and BytesIO has none of its own
    buffer.name = "speech.wav"

    async with AsyncOpenAI(api_key=api_key) as client:
        try:
            result = await client.audio.transcriptions.create(
                model=config.TRANSCRIBE_MODEL, file=buffer
            )
        except openai.APIError as exc:
            raise _upstream(exc) from exc

    return result.text.strip()


async def speak(text: str, api_key: str) -> AsyncIterator[bytes]:
    """Raw 24 kHz pcm as it arrives. The request is opened before this returns, so a
    rejected key is still an error status rather than an empty stream."""
    stack = AsyncExitStack()
    try:
        client = await stack.enter_async_context(AsyncOpenAI(api_key=api_key))
        response = await stack.enter_async_context(
            client.audio.speech.with_streaming_response.create(
                model=config.SPEAK_MODEL,
                voice=config.SPEAK_VOICE,
                input=text[: config.MAX_SPEAK_CHARS],
                response_format="pcm",
                speed=config.SPEAK_SPEED,
            )
        )
    except openai.APIError as exc:
        await stack.aclose()
        raise _upstream(exc) from exc

    async def body() -> AsyncIterator[bytes]:
        async with stack:
            async for chunk in response.iter_bytes(config.CHUNK_BYTES):
                yield chunk

    return body()


def _upstream(exc: openai.APIError) -> Exception:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return ConflictError(
            message="Your OpenAI key was rejected. Ask an owner or admin to issue a new one.",
            code="voice_key_rejected",
        )

    return ServiceUnavailableError(
        message="Voice is unavailable right now, try again", code="voice_unavailable"
    )
