"""Files the user attaches to a message: an image to look at, a PDF to read, a file to use.

An attachment is uploaded into the user's drafts project first (Borradores/adjuntos/), so
it is an ordinary project file -- the agent can put it in a page by its path, move it,
convert it. The message stores only a reference to it:

    {"type": "attachment", "file_id": ..., "project": "Borradores",
     "path": "adjuntos/gato.png", "name": "gato.png", "content_type": "image/png", ...}

Only when the conversation is sent to the model is the reference opened up (expand):
a note saying where the file is, then what is in it -- the image itself, or the text of
a PDF, Word or text file. The stored thread stays small; the model still sees the file.
"""

import asyncio
import base64
import io
import tempfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from src.core.llm.domain import Message

from . import config

ATTACHMENT = "attachment"

# What the model is shown as a picture. Anything else is described by its text, or only
# by where it is.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# (bytes, content type) of a file by its id, or None when it cannot be had.
LoadFn = Callable[[UUID], Awaitable[tuple[bytes, str] | None]]

# Images made ready for the model, by file: resizing is the slow part, and a conversation
# sends the same image again on every turn.
_prepared: OrderedDict[tuple[UUID, str], dict[str, Any]] = OrderedDict()


def is_attachment(block: object) -> bool:
    return isinstance(block, dict) and block.get("type") == ATTACHMENT


def attachments_in(message: Message) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if is_attachment(block)]


def user_message(text: str, attachments: Sequence[dict[str, Any]]) -> Message:
    """The message as stored: plain text when nothing is attached, else text and references."""
    if not attachments:
        return {"role": "user", "content": text}
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text.strip() else []
    return {"role": "user", "content": [*blocks, *attachments]}


async def expand(history: Sequence[Message], load: LoadFn) -> list[Message]:
    """The history as the model is sent it: every attachment opened up. Images only in the
    latest few messages that have any -- each is re-sent on every turn, and further back a
    note of where it is serves as well."""
    with_files = [index for index, message in enumerate(history) if attachments_in(message)]
    if not with_files:
        return list(history)
    shown = set(with_files[-config.ATTACHMENT_IMAGE_MESSAGES :])

    expanded: list[Message] = []
    for index, message in enumerate(history):
        if index not in with_files:
            expanded.append(message)
            continue
        blocks: list[dict[str, Any]] = []
        for block in message["content"]:
            if is_attachment(block):
                blocks.extend(await _open(block, load, picture=index in shown))
            else:
                blocks.append(block)
        expanded.append({**message, "content": blocks})
    return expanded


async def _open(block: dict[str, Any], load: LoadFn, picture: bool) -> list[dict[str, Any]]:
    where = f"{block.get('project')}/{block.get('path')}"
    content_type = str(block.get("content_type") or "application/octet-stream")
    note = (
        f"[The user attached the file '{block.get('name')}' ({content_type}, "
        f"{_size(block.get('size_bytes'))}). It is saved in their projects at {where} -- "
        "work with it by that path: in a page in the same project, point at it by its "
        "relative path from the page.]"
    )

    try:
        file_id = UUID(str(block.get("file_id")))
    except ValueError:
        return [_text(note)]

    if content_type in IMAGE_TYPES:
        if not picture:
            return [_text(note + " (An image shown earlier in the conversation.)")]
        image = await _image(file_id, load)
        return [_text(note), image] if image else [_text(note + " (It could not be opened.)")]

    text = await _contents(file_id, str(block.get("name") or ""), load)
    if text is None:
        return [_text(note)]
    if len(text) > config.ATTACHMENT_TEXT_CHARS:
        text = text[: config.ATTACHMENT_TEXT_CHARS] + (
            f"\n\n[... cut off here: only the first {config.ATTACHMENT_TEXT_CHARS:,} characters "
            f"are shown. The whole file is at {where}.]"
        )
    return [_text(f"{note}\n\nWhat it says:\n\n{text}")]


async def _image(file_id: UUID, load: LoadFn) -> dict[str, Any] | None:
    key = (file_id, "image")
    if key in _prepared:
        _prepared.move_to_end(key)
        return _prepared[key]

    loaded = await load(file_id)
    if loaded is None:
        return None
    data, content_type = loaded
    try:
        data, content_type = await asyncio.to_thread(_fit, data, content_type)
    except Exception:  # noqa: BLE001 -- a picture that will not decode is described, not sent
        return None

    image = {"type": "image", "base64": base64.b64encode(data).decode("ascii"), "mime_type": content_type}
    _prepared[key] = image
    while len(_prepared) > config.ATTACHMENT_CACHE_SIZE:
        _prepared.popitem(last=False)
    return image


def _fit(data: bytes, content_type: str) -> tuple[bytes, str]:
    """The image no bigger than the models look at: past ATTACHMENT_IMAGE_MAX_SIDE pixels
    they scale it down themselves, and a large file only costs time to send. One within
    both limits goes as it is."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        small_enough = max(image.size) <= config.ATTACHMENT_IMAGE_MAX_SIDE
        if small_enough and len(data) <= config.ATTACHMENT_IMAGE_MAX_BYTES:
            return data, content_type

        image.thumbnail((config.ATTACHMENT_IMAGE_MAX_SIDE, config.ATTACHMENT_IMAGE_MAX_SIDE))
        out = io.BytesIO()
        if image.mode in ("RGBA", "LA", "P"):
            image.save(out, format="PNG", optimize=True)
            return out.getvalue(), "image/png"
        image.convert("RGB").save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"


async def _contents(file_id: UUID, name: str, load: LoadFn) -> str | None:
    """A PDF's, Word document's or text file's text; None for anything else."""
    from src.documents import extraction

    if extraction.suffix_of(name) not in (
        extraction.PDF_SUFFIXES | extraction.WORD_SUFFIXES | extraction.TEXT_SUFFIXES
    ):
        return None
    loaded = await load(file_id)
    if loaded is None:
        return None

    def read(data: bytes) -> str | None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "attachment"
            source.write_bytes(data)
            try:
                return extraction.extract(source, name)
            except Exception:  # noqa: BLE001 -- unreadable: the note alone still says where it is
                return None

    return await asyncio.to_thread(read, loaded[0])


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _size(size: object) -> str:
    if not isinstance(size, int):
        return "size unknown"
    if size < 1024 * 1024:
        return f"{max(1, size // 1024)} KB"
    return f"{size / (1024 * 1024):.1f} MB"
