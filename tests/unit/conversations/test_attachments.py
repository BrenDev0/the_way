import base64
import io
from uuid import uuid4

from PIL import Image

from src.conversations import attachments, config


def png(width=40, height=30) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


def reference(file_id, name, content_type, size=1234):
    return {
        "type": "attachment", "file_id": str(file_id), "project": "Borradores",
        "path": f"adjuntos/{name}", "name": name, "content_type": content_type, "size_bytes": size,
    }


class Loader:
    def __init__(self, files):
        self.files = files
        self.loaded = []

    async def __call__(self, file_id):
        self.loaded.append(file_id)
        return self.files.get(file_id)


def test_a_message_without_files_stays_plain_text():
    assert attachments.user_message("hola", []) == {"role": "user", "content": "hola"}


def test_a_message_with_files_keeps_text_and_references():
    ref = reference(uuid4(), "gato.png", "image/png")

    assert attachments.user_message("ponla en el pdf", [ref]) == {
        "role": "user",
        "content": [{"type": "text", "text": "ponla en el pdf"}, ref],
    }
    # a picture alone is a message too
    assert attachments.user_message("  ", [ref])["content"] == [ref]


async def test_an_attached_image_goes_to_the_model_as_a_picture_and_says_where_it_is():
    file_id = uuid4()
    image = png()
    history = [attachments.user_message("¿qué es esto?", [reference(file_id, "gato.png", "image/png")])]

    expanded = await attachments.expand(history, Loader({file_id: (image, "image/png")}))

    text, note, picture = expanded[0]["content"]
    assert text == {"type": "text", "text": "¿qué es esto?"}
    assert "Borradores/adjuntos/gato.png" in note["text"]
    assert picture == {"type": "image", "base64": base64.b64encode(image).decode(), "mime_type": "image/png"}


async def test_the_stored_history_is_left_as_it_was():
    file_id = uuid4()
    history = [attachments.user_message("mira", [reference(file_id, "a.png", "image/png")])]
    before = [dict(message) for message in history]

    await attachments.expand(history, Loader({file_id: (png(), "image/png")}))

    assert history == before


async def test_a_large_image_is_scaled_down_before_it_is_sent():
    file_id = uuid4()
    history = [attachments.user_message("", [reference(file_id, "big.png", "image/png")])]

    expanded = await attachments.expand(history, Loader({file_id: (png(4000, 3000), "image/png")}))

    picture = expanded[0]["content"][-1]
    with Image.open(io.BytesIO(base64.b64decode(picture["base64"]))) as sent:
        assert max(sent.size) == config.ATTACHMENT_IMAGE_MAX_SIDE


async def test_older_images_are_only_mentioned():
    ids = [uuid4() for _ in range(config.ATTACHMENT_IMAGE_MESSAGES + 1)]
    history = []
    for file_id in ids:
        history += [attachments.user_message("x", [reference(file_id, "p.png", "image/png")]), {"role": "assistant", "content": "ok"}]
    loader = Loader({file_id: (png(), "image/png") for file_id in ids})

    expanded = await attachments.expand(history, loader)

    oldest = expanded[0]["content"]
    assert all(block["type"] == "text" for block in oldest)
    assert "shown earlier" in oldest[-1]["text"]
    assert ids[0] not in loader.loaded
    assert expanded[-2]["content"][-1]["type"] == "image"


async def test_a_text_file_is_read_to_the_model():
    file_id = uuid4()
    history = [attachments.user_message("resume", [reference(file_id, "notas.md", "text/markdown")])]

    expanded = await attachments.expand(history, Loader({file_id: (b"# Plan\nVender mas en Merida.", "text/markdown")}))

    assert "Vender mas en Merida." in expanded[0]["content"][-1]["text"]


async def test_a_long_file_is_cut_off_and_says_so():
    file_id = uuid4()
    history = [attachments.user_message("", [reference(file_id, "largo.txt", "text/plain")])]
    long_text = ("palabra " * (config.ATTACHMENT_TEXT_CHARS // 4)).encode()

    expanded = await attachments.expand(history, Loader({file_id: (long_text, "text/plain")}))

    assert "cut off here" in expanded[0]["content"][-1]["text"]


async def test_a_file_that_cannot_be_read_is_still_said_to_be_there():
    file_id = uuid4()
    history = [attachments.user_message("", [reference(file_id, "video.mp4", "video/mp4")])]
    loader = Loader({})

    expanded = await attachments.expand(history, loader)

    (note,) = expanded[0]["content"]
    assert "Borradores/adjuntos/video.mp4" in note["text"]
    assert loader.loaded == []
