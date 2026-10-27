"""Getting the words out of a video or a recording: a platform's own captions when it has
them, otherwise the audio, downloaded and transcribed.

Everything here can fail for reasons outside our control -- a platform blocks servers, a
video has no captions, a post is private -- and each failure says which, so the agent can
tell the user plainly and fall back to asking for a pasted transcript.
"""

import asyncio
import io
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import openai
from openai import AsyncOpenAI

from . import config


class Unavailable(Exception):
    """No transcript from this source, and why -- said to the user as it is."""


@dataclass(frozen=True)
class Transcript:
    text: str
    title: str
    # how it was made: the platform's captions (and whether they were automatic), or the
    # audio transcribed
    how: str


def platform_of(url: str) -> str | None:
    """The platform a link is on, when it is one we fetch from; None for anything else."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    for platform in config.PLATFORM_HOSTS:
        if host == platform or host.endswith("." + platform):
            return platform
    return None


_YOUTUBE_ID = re.compile(r"^[\w-]{11}$")


def youtube_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    candidate = None
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                candidate = parts[1]
    return candidate if candidate and _YOUTUBE_ID.match(candidate) else None


def _captions(video_id: str, language: str | None) -> Transcript:
    from youtube_transcript_api import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )

    try:
        listed = YouTubeTranscriptApi().list(video_id)
        wanted = [language] if language else []
        chosen = None
        if wanted:
            try:
                chosen = listed.find_transcript(wanted)
            except NoTranscriptFound:
                chosen = None
        # a person's captions before automatic ones, in whatever language the video has
        chosen = chosen or next((t for t in listed if not t.is_generated), None) or next(iter(listed), None)
        if chosen is None:
            raise Unavailable("the video has no captions")
        fetched = chosen.fetch()
    except (RequestBlocked, IpBlocked) as exc:
        raise Unavailable("YouTube refused this server's request for the captions") from exc
    except TranscriptsDisabled as exc:
        raise Unavailable("captions are turned off for this video") from exc
    except Unavailable:
        raise
    except Exception as exc:  # private, removed, region-locked...
        raise Unavailable(f"the captions could not be read ({type(exc).__name__})") from exc

    text = " ".join(" ".join(snippet.text.split()) for snippet in fetched if snippet.text.strip())
    kind = "automatic captions" if chosen.is_generated else "captions"
    return Transcript(text=text, title="", how=f"YouTube's {kind} ({chosen.language_code})")


async def captions(video_id: str, language: str | None) -> Transcript:
    return await asyncio.to_thread(_captions, video_id, language)


def _download(url: str, folder: str) -> tuple[Path, str]:
    import yt_dlp  # type: ignore[import-untyped]

    options = {
        "format": "bestaudio[filesize<25M]/bestaudio[filesize_approx<25M]/bestaudio/worst",
        "outtmpl": f"{folder}/audio.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": config.MAX_AUDIO_BYTES,
        "socket_timeout": 20,
        "allowed_extractors": list(config.EXTRACTORS),
        "postprocessors": [],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise Unavailable("nothing to download at that link")
            duration = info.get("duration") or 0
            if duration > config.MAX_SECONDS:
                raise Unavailable(
                    f"it is {duration // 60} minutes long, over the {config.MAX_SECONDS // 60}-minute limit"
                )
            ydl.process_info(info)
    except Unavailable:
        raise
    except Exception as exc:  # yt-dlp raises its own kinds for every failure
        message = " ".join(str(exc).replace("ERROR:", "").split())[:200]
        raise Unavailable(f"the audio could not be downloaded ({message})") from exc

    files = sorted(Path(folder).glob("audio.*"))
    if not files:
        raise Unavailable(f"the audio is over the {config.MAX_AUDIO_BYTES // (1024 * 1024)} MB limit")
    return files[0], str(info.get("title") or "")


async def transcribe(data: bytes, filename: str, api_key: str, language: str | None) -> str:
    if len(data) > config.MAX_AUDIO_BYTES:
        raise Unavailable(f"the audio is over the {config.MAX_AUDIO_BYTES // (1024 * 1024)} MB limit")
    client = AsyncOpenAI(api_key=api_key, timeout=config.REQUEST_TIMEOUT_SECONDS)
    last: Exception | None = None
    for model in (config.TRANSCRIBE_MODEL, config.FALLBACK_MODEL):
        buffer = io.BytesIO(data)
        # the API picks its decoder off the file name
        buffer.name = filename
        try:
            result = await client.audio.transcriptions.create(
                model=model, file=buffer, language=language or openai.omit
            )
            return result.text.strip()
        except openai.BadRequestError as exc:
            last = exc  # too long for this model, say: the next one may take it
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise Unavailable("the OpenAI key was refused") from exc
        except openai.APIError as exc:
            raise Unavailable(f"OpenAI could not transcribe it ({type(exc).__name__})") from exc
    raise Unavailable(f"OpenAI would not transcribe this audio ({last})")


async def from_link(url: str, api_key: str | None, language: str | None) -> Transcript:
    """Captions when the link is a YouTube video that has them; otherwise the audio,
    transcribed. Says why when neither works."""
    caption_problem = None
    if (video := youtube_id(url)) is not None:
        try:
            return await captions(video, language)
        except Unavailable as exc:
            caption_problem = str(exc)

    if api_key is None:
        reason = f"{caption_problem}, and " if caption_problem else ""
        raise Unavailable(f"{reason}transcribing the audio needs an OpenAI key, and none has been set up for this organization")

    with tempfile.TemporaryDirectory() as folder:
        try:
            path, title = await asyncio.to_thread(_download, url, folder)
        except Unavailable as exc:
            raise Unavailable(f"{caption_problem}; and {exc}" if caption_problem else str(exc)) from exc
        text = await transcribe(path.read_bytes(), path.name, api_key, language)
    return Transcript(text=text, title=title, how="the audio, transcribed")
