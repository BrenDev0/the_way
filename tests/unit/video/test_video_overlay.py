import io
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from helpers import FakeBucketStore, make_tool_ports
from PIL import Image

from src.assistants.context import ToolContext
from src.background import config as background_config
from src.core.exceptions import NotFoundError
from src.video import overlay
from src.video import tools as video_tools
from src.video.tool_schemas import AddTextToVideo, GenerateVideo

CLIP = b"fake mp4 bytes"


def probed(width=480, height=848, seconds=13.0, rotation=None):
    stream = {"codec_type": "video", "width": width, "height": height}
    if rotation is not None:
        stream["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": rotation}]
    return json.dumps({"streams": [{"codec_type": "audio"}, stream], "format": {"duration": str(seconds)}}).encode()


@pytest.fixture
def ffmpeg(monkeypatch):
    state = SimpleNamespace(calls=[], probe=probed(), code=0, pictures={})

    async def fake(args, timeout):
        state.calls.append(args)
        if args[0] == "ffprobe":
            return 0, state.probe, b""
        for index, arg in enumerate(args):
            if arg == "-i" and args[index + 1].endswith(".png"):
                state.pictures[args[index + 1]] = Image.open(args[index + 1]).size
        if state.code == 0:
            Path(args[-1]).write_bytes(b"result mp4")
        return state.code, b"", b"boom: bad filter"

    monkeypatch.setattr(overlay, "_exec", fake)
    return state


class FakeFiles:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.written = {}

    async def project(self, name):
        return SimpleNamespace(name=name)

    async def source(self, project, path):
        return project, path

    async def entry(self, project, path):
        if f"{project.name}/{path}" in self.existing:
            return video_tools.ProjectFile.__new__(video_tools.ProjectFile)
        raise NotFoundError("no such folder")

    async def read_bytes(self, project, path, limit):
        return SimpleNamespace(name=path), CLIP

    async def write(self, project, path, content, overwrite=False, content_type=None):
        self.written[f"{project.name}/{path}"] = (content, content_type)
        return SimpleNamespace(size_bytes=len(content))


def context(files):
    return ToolContext(
        should_stop=None, files=files, ports=make_tool_ports(), organization_id=uuid4(), user_id=uuid4(),  # type: ignore[arg-type]
        user_role="member", bucket_store=FakeBucketStore(), credentials={},
        llm_factory=None,  # type: ignore[arg-type]
    )


def handler(files):
    return video_tools.build_local(context(files))["AddTextToVideo"].handler


def card(**kwargs):
    return {"text": "Tu empresa, con compromiso", **kwargs}


async def test_every_text_becomes_a_picture_the_size_of_the_clip_laid_over_it(ffmpeg):
    files = FakeFiles()

    result = await handler(files)(
        project="Campana", video_path="clip.mp4",
        texts=[card(end_seconds=4), card(text="Escríbenos por WhatsApp", start_seconds=5, position="top")],
        box="black",
    )

    command = ffmpeg.calls[1]
    assert command[0] == "ffmpeg" and command.count("-loop") == 2
    assert set(ffmpeg.pictures.values()) == {(480, 848)}
    graph = command[command.index("-filter_complex") + 1]
    assert "between(t,0.000,4.000)" in graph and "between(t,5.000,13.000)" in graph
    assert "fade=t=in:st=5.000" in graph
    assert command[command.index("-c:a") + 1] == "copy" and "0:a?" in command
    assert files.written == {"Campana/clip-con-texto.mp4": (b"result mp4", "video/mp4")}
    assert "Campana/clip-con-texto.mp4" in result and "2 texts" in result and "480x848" in result


async def test_the_text_picture_is_transparent_with_the_words_drawn_on_it(ffmpeg, monkeypatch):
    drawn = {}
    original = overlay._card_picture

    def spy(info, card_, style):
        picture = original(info, card_, style)
        drawn["image"] = Image.open(io.BytesIO(picture))
        return picture

    monkeypatch.setattr(overlay, "_card_picture", spy)
    await handler(FakeFiles())(project="Campana", video_path="clip.mp4", texts=[card()], color="white")

    image = drawn["image"]
    assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0
    assert image.getchannel("A").getbbox() is not None
    assert image.getchannel("A").getbbox()[1] > image.height // 2


async def test_a_phone_clip_that_is_turned_is_measured_as_it_is_seen(ffmpeg):
    ffmpeg.probe = probed(width=1920, height=1080, rotation=-90)

    await handler(FakeFiles())(project="Campana", video_path="clip.mp4", texts=[card()])

    assert set(ffmpeg.pictures.values()) == {(1080, 1920)}


async def test_text_that_starts_after_the_clip_ends_is_refused_with_the_reason(ffmpeg):
    files = FakeFiles()

    result = await handler(files)(project="Campana", video_path="clip.mp4", texts=[card(start_seconds=20)])

    assert "starts at 20s but the clip is only 13.0s long" in result
    assert files.written == {}


async def test_an_end_before_the_start_is_refused(ffmpeg):
    result = await handler(FakeFiles())(
        project="Campana", video_path="clip.mp4", texts=[card(start_seconds=6, end_seconds=3)]
    )

    assert "must end after it starts" in result


async def test_an_ffmpeg_failure_is_said_to_the_model_and_nothing_is_saved(ffmpeg):
    ffmpeg.code = 1
    files = FakeFiles()

    result = await handler(files)(project="Campana", video_path="clip.mp4", texts=[card()])

    assert result.startswith("Could not add the text") and "bad filter" in result
    assert files.written == {}


async def test_a_file_that_is_not_a_video_is_said_so(ffmpeg):
    ffmpeg.probe = json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "3"}}).encode()

    result = await handler(FakeFiles())(project="Campana", video_path="song.mp3", texts=[card()])

    assert "no video to put text on" in result


async def test_a_file_already_there_is_not_replaced_unless_asked(ffmpeg):
    files = FakeFiles(existing={"Campana/clip-con-texto.mp4"})

    refused = await handler(files)(project="Campana", video_path="clip.mp4", texts=[card()])
    replaced = await handler(files)(project="Campana", video_path="clip.mp4", texts=[card()], overwrite=True)

    assert "already exists" in refused and "overwrite=true" in refused
    assert "Saved Campana/clip-con-texto.mp4" in replaced and list(files.written) == ["Campana/clip-con-texto.mp4"]


async def test_a_missing_ffmpeg_is_a_message_not_a_crash(monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(overlay.asyncio, "create_subprocess_exec", missing)

    result = await handler(FakeFiles())(project="Campana", video_path="clip.mp4", texts=[card()])

    assert "not installed on the server" in result


def test_it_needs_no_fal_key_and_no_approval_and_a_task_may_use_it():
    ctx = context(FakeFiles())
    tool = video_tools.build_local(ctx)["AddTextToVideo"]

    assert not video_tools.available(ctx)
    assert not tool.requires_approval and not tool.always_ask
    assert "AddTextToVideo" in background_config.TOOLS


def test_the_video_prompt_tells_the_model_never_to_ask_for_text():
    assert "NEVER ask for readable" in GenerateVideo.model_fields["prompt"].description
    assert AddTextToVideo.model_json_schema()["properties"]["texts"]["minItems"] == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed here")
async def test_with_the_real_ffmpeg_the_text_really_lands_on_the_frames(tmp_path):
    source = tmp_path / "in.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=10",
         "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-pix_fmt", "yuv420p", str(source)],
        check=True,
    )

    made, info = await overlay.burn_text(
        source.read_bytes(), [overlay.Card("Hola ñandú", 0.5, 1.5, "center")], overlay.Style(fade=0)
    )

    out = tmp_path / "out.mp4"
    out.write_bytes(made)
    assert (info.width, info.height) == (320, 240)
    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(frame)], check=True)
    pixels = Image.open(frame).convert("RGB").getdata()
    assert any(r > 200 and g > 200 and b > 200 for r, g, b in pixels)
    audio = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-select_streams", "a", str(out)], capture_output=True)
    assert b"codec_type=audio" in audio.stdout
