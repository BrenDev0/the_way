from uuid import uuid4

import pytest
from helpers import make_api_key

from src.api_keys.domain import Provider
from src.conversations import prompt
from src.core.exceptions import ConflictError, ValidationError
from src.voice import config
from src.voice import use_cases as voice_use_cases


def listing(*keys):
    async def list_api_keys_for_user_fn(user_id):
        return list(keys)

    return list_api_keys_for_user_fn


async def test_voice_uses_the_openai_key_even_when_anthropic_is_issued(encryption_service):
    user_id = uuid4()
    keys = listing(
        make_api_key(user_id=user_id, provider=Provider.ANTHROPIC),
        make_api_key(
            user_id=user_id,
            provider=Provider.OPENAI,
            encrypted_secret=encryption_service.encrypt("sk-openai"),
        ),
    )

    assert await voice_use_cases.openai_key(user_id, keys, encryption_service) == "sk-openai"


async def test_voice_without_an_openai_key_is_refused(encryption_service):
    keys = listing(make_api_key(provider=Provider.ANTHROPIC))

    with pytest.raises(ConflictError) as exc:
        await voice_use_cases.openai_key(uuid4(), keys, encryption_service)

    assert exc.value.code == "voice_key_not_configured"


async def test_a_recording_too_short_to_be_speech_is_not_sent():
    assert await voice_use_cases.transcribe(b"\0" * (config.MIN_AUDIO_BYTES - 1), "sk") == ""


async def test_an_oversized_recording_is_refused():
    with pytest.raises(ValidationError):
        await voice_use_cases.transcribe(b"\0" * (config.MAX_AUDIO_BYTES + 1), "sk")


def test_the_agent_is_told_which_local_folder_is_open_now():
    opened = prompt.turn_context("Monday", "", [], desktop=True, local_folder="C:/Users/me/Desktop")
    none = prompt.turn_context("Monday", "", [], desktop=True, local_folder="")
    unknown = prompt.turn_context("Monday", "", [], desktop=True)

    assert "open in the desktop app right now is: C:/Users/me/Desktop" in opened
    assert "try again now" in opened  # an earlier "no folder" must not stick
    assert "No folder is open" in none
    # an app too old to say leaves the agent to find out by trying, as before
    assert "folder" not in unknown.lower()


def test_a_remote_working_folder_becomes_where_work_goes_by_default():
    text = prompt.turn_context("Monday", "", [], desktop=True, remote_folder="cx/nuevo_prueba")

    assert "the project 'cx', folder 'nuevo_prueba'" in text
    assert "deliver_to_project='cx' and deliver_to_path='nuevo_prueba'" in text
    assert "open in the desktop app right now" not in text  # it replaces the local line


def test_a_voice_turn_asks_for_a_spoken_reply():
    spoken = prompt.turn_context("Monday", "", [], desktop=True, voice=True)
    written = prompt.turn_context("Monday", "", [], desktop=True)

    assert prompt.VOICE_STYLE in spoken
    assert prompt.VOICE_STYLE not in written


def test_a_key_keeps_its_client_so_its_connection_stays_warm():
    first = voice_use_cases._client("sk-one")

    assert voice_use_cases._client("sk-one") is first
    assert voice_use_cases._client("sk-two") is not first


def test_the_oldest_client_is_let_go_past_the_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_CLIENTS", 2)
    monkeypatch.setattr(voice_use_cases, "_clients", type(voice_use_cases._clients)())

    oldest = voice_use_cases._client("sk-a")
    voice_use_cases._client("sk-b")
    voice_use_cases._client("sk-c")

    assert len(voice_use_cases._clients) == 2
    assert voice_use_cases._client("sk-a") is not oldest
