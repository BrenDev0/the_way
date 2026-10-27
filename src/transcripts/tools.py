import re
from datetime import UTC, datetime

from src.api_keys.domain import Provider
from src.assistants.context import ToolContext
from src.core.exceptions import ApplicationError
from src.core.tools.domain import Tool
from src.projects.files import ProjectFiles
from src.projects.html_images import project_ref

from . import config, fetch
from .tool_schemas import TranscribeMedia

NOT_A_SOURCE = (
    "'{source}' is not a link this can fetch from, nor a project file. Links: a post on "
    "{platforms}. Files: project:<project>/<path>, an audio or video file. For anything "
    "else, ask the user to paste the transcript or to upload the recording to a project."
)

COULD_NOT = (
    "No transcript: {reason}. Tell the user plainly, and ask them to paste the transcript "
    "(on YouTube: '...more' under the video, then 'Show transcript') or to upload the "
    "recording to a project. Do not write a transcript yourself."
)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50].rstrip("-")
    return cleaned or "transcript"


def build(context: ToolContext) -> dict[str, Tool]:
    files = context.files
    credential = context.credentials.get(str(Provider.OPENAI))
    api_key = credential.secret if credential else None

    async def transcribe_media(source: str, language: str | None = None) -> str:
        source = source.strip()
        language = (language or "").strip().lower()[:5] or None
        try:
            if (ref := project_ref(source)) is not None:
                transcript = await _from_project(files, ref, api_key, language)
            elif fetch.platform_of(source) is not None:
                transcript = await fetch.from_link(source, api_key, language)
            else:
                return NOT_A_SOURCE.format(source=source[:200], platforms=", ".join(config.PLATFORM_HOSTS))
        except fetch.Unavailable as exc:
            return COULD_NOT.format(reason=exc)
        except ApplicationError as exc:  # the project file: not there, a folder, too big
            return COULD_NOT.format(reason=exc.message)
        if not transcript.text:
            return COULD_NOT.format(reason="the transcript came back empty -- there may be no speech in it")

        name = f"{_slug(transcript.title or source.rsplit('/', 1)[-1])}-{datetime.now(UTC):%Y%m%d-%H%M%S}.txt"
        header = f"Source: {source}\nTitle: {transcript.title or '(none)'}\nFrom: {transcript.how}\n\n"
        workspace = await files.workspace()
        await files.write(workspace, f"{config.FOLDER}/{name}", (header + transcript.text).encode("utf-8"))

        shown = transcript.text[: config.MAX_RETURNED_CHARS]
        more = (
            f"\n\n[... {len(transcript.text) - len(shown):,} more characters in the saved file.]"
            if len(shown) < len(transcript.text)
            else ""
        )
        return (
            f"Transcript of {source} ({transcript.how}; {len(transcript.text):,} characters), saved as "
            f".the_way/{config.FOLDER}/{name} -- read it from there rather than fetching it again.\n\n"
            f"{shown}{more}"
        )

    return {TranscribeMedia.__name__: Tool(schema=TranscribeMedia, handler=transcribe_media)}


async def _from_project(
    files: ProjectFiles, ref: tuple[str, str], api_key: str | None, language: str | None
) -> fetch.Transcript:
    name, path = ref
    project = next((held for held in await files.projects() if held.name.lower() == name.lower()), None)
    if project is None:
        raise fetch.Unavailable(f"there is no project named '{name}'")
    entry = await files.file(project, path)
    if not entry.content_type.startswith(config.AUDIO_TYPES) and not path.lower().endswith(config.AUDIO_SUFFIXES):
        raise fetch.Unavailable(f"'{path}' is {entry.content_type}, not audio or video")
    if api_key is None:
        raise fetch.Unavailable("transcribing needs an OpenAI key, and none has been set up for this organization")
    _entry, data = await files.read_bytes(project, path, limit=config.MAX_AUDIO_BYTES)
    text = await fetch.transcribe(data, path.rsplit("/", 1)[-1], api_key, language)
    return fetch.Transcript(text=text, title=path.rsplit("/", 1)[-1], how="the recording, transcribed")
