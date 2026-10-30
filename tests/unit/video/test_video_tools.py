"""The video tools against a stand-in for fal: sources uploaded to fal storage, the job
submitted to the queue, polled while it works, and the clip downloaded into the project."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from helpers import FakeBucketStore, make_tool_ports

from src.assistants.context import Credential, ToolContext
from src.background import config as background_config
from src.core.llm.domain import ToolCall
from src.core.tools.domain import ClientActionRequired, ClientRequest
from src.core.tools.gates import Allowance, AllowanceGate
from src.images import config as images_config
from src.video import config as video_config
from src.video import tools as video_tools

CLIP = b"\x00\x00\x00\x18ftypmp42 fake clip"


class FakeFiles:
    """Just what the video tools touch of ProjectFiles."""

    def __init__(self) -> None:
        self.stored = {("Campana", "fotos/gato.png"): (b"png-bytes", "image/png"),
                       ("Borradores", "clip.mp4"): (b"mp4-bytes", "video/mp4")}
        self.written: dict[str, tuple[bytes, str]] = {}

    async def project(self, name: str):
        if name not in {"Campana", "Borradores"}:
            raise LookupError(f"No project named '{name}'")
        return SimpleNamespace(name=name)

    async def source(self, project, path: str):
        if path.startswith("project:"):
            name, inner = path.removeprefix("project:").split("/", 1)
            return SimpleNamespace(name=name), inner
        return project, path

    async def read_bytes(self, project, path: str, limit: int):
        data, content_type = self.stored[(project.name, path)]
        return SimpleNamespace(name=path.rsplit("/", 1)[-1], content_type=content_type), data

    async def write(self, project, path: str, content: bytes, overwrite: bool = False, content_type=None):
        self.written[f"{project.name}/{path}"] = (content, content_type)
        return SimpleNamespace(size_bytes=len(content))


def context(files: FakeFiles, credentials: dict | None = None) -> ToolContext:
    return ToolContext(
        files=files,  # type: ignore[arg-type]
        ports=make_tool_ports(),
        organization_id=uuid4(),
        user_id=uuid4(),
        user_role="member",
        bucket_store=FakeBucketStore(),
        credentials={"fal": Credential(secret="fal-test")} if credentials is None else credentials,
        llm_factory=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def fal(monkeypatch):
    state = {"polls": 2, "submit_status": 200, "result": {"video": {"url": "https://cdn.fal/out.mp4"}}}
    seen: list[tuple[str, str, dict | None]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content) if request.content and request.method == "POST" else None
        seen.append((request.method, url, body))
        if url.startswith("https://rest.fal.ai/storage/upload/initiate"):
            assert request.headers["Authorization"] == "Key fal-test"
            return httpx.Response(200, json={
                "upload_url": f"https://upload.fal/{body['file_name']}",
                "file_url": f"https://files.fal/{body['file_name']}",
            })
        if url.startswith("https://upload.fal/"):
            return httpx.Response(200)
        if url == "https://cdn.fal/out.mp4":
            assert "Authorization" not in request.headers  # fal's key goes only to fal's API
            return httpx.Response(200, content=CLIP)
        assert request.headers["Authorization"] == "Key fal-test"
        if request.method == "POST":
            if state["submit_status"] != 200:
                return httpx.Response(state["submit_status"], json={"detail": "nope"})
            return httpx.Response(200, json={
                "request_id": "r1",
                "status_url": "https://queue.fal.run/x/requests/r1/status",
                "response_url": "https://queue.fal.run/x/requests/r1",
            })
        if url.endswith("/status"):
            if state["polls"]:
                state["polls"] -= 1
                return httpx.Response(202, json={"status": "IN_PROGRESS"})
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(200, json=state["result"])

    real = httpx.AsyncClient
    monkeypatch.setattr(
        video_tools.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handle), **kwargs)
    )
    monkeypatch.setattr(video_config, "POLL_SECONDS", 0)
    return SimpleNamespace(seen=seen, state=state)


async def test_a_video_from_text_is_submitted_polled_and_saved_as_mp4(fal):
    files = FakeFiles()
    generate = video_tools.build(context(files))["GenerateVideo"].handler

    result = await generate(
        project="Campana", prompt="un gato en la playa", output_path="teaser",
        seconds=40, aspect_ratio="9:16", model="kling-4",
    )

    submit = fal.seen[0]
    assert submit[1] == "https://queue.fal.run/kling/v4/text-to-video"
    # clamped to what Kling 4 makes, and as the integer it takes
    assert submit[2] == {"prompt": "un gato en la playa", "duration": 30, "aspect_ratio": "9:16"}
    assert [url for _, url, _ in fal.seen].count("https://queue.fal.run/x/requests/r1/status") == 3
    assert files.written == {"Campana/teaser.mp4": (CLIP, "video/mp4")}
    assert "Kling 4.0 (kling-4)" in result and "Campana/teaser.mp4" in result


async def test_each_model_gets_its_own_inputs(fal):
    files = FakeFiles()
    generate = video_tools.build(context(files))["GenerateVideo"].handler

    await generate(project="Campana", prompt="p", output_path="a.mp4", seconds=8, aspect_ratio="21:9", model="kling-3")

    # Kling 3 takes the length as a string, and has no 21:9
    assert fal.seen[0][1] == "https://queue.fal.run/fal-ai/kling-video/v3/pro/text-to-video"
    assert fal.seen[0][2] == {"prompt": "p", "duration": "8"}


async def test_an_image_from_another_project_is_uploaded_and_animated(fal):
    files = FakeFiles()
    animate = video_tools.build(context(files))["AnimateImage"].handler

    await animate(
        project="Borradores", image_path="project:Campana/fotos/gato.png",
        prompt="el gato salta", output_path="gato.mp4", model="seedance-2.5",
    )

    submit = next(entry for entry in fal.seen if entry[1].startswith("https://queue.fal.run/bytedance"))
    assert submit[1] == "https://queue.fal.run/bytedance/seedance-2.5/image-to-video"
    assert submit[2] == {"prompt": "el gato salta", "image_url": "https://files.fal/gato.png"}
    assert "Borradores/gato.mp4" in files.written


async def test_a_clip_is_edited_with_kling_omni(fal):
    files = FakeFiles()
    edit = video_tools.build(context(files))["EditVideo"].handler

    await edit(
        project="Borradores", video_path="clip.mp4", prompt="@Video1 de noche",
        output_path="clip-noche.mp4", model="kling-omni",
    )

    submit = next(entry for entry in fal.seen if entry[1].startswith("https://queue.fal.run/fal-ai"))
    assert submit[1] == "https://queue.fal.run/fal-ai/kling-video/o3/standard/video-to-video/edit"
    assert submit[2] == {"prompt": "@Video1 de noche", "video_url": "https://files.fal/clip.mp4"}


async def test_a_refusal_comes_back_as_text_the_model_can_act_on(fal):
    fal.state["submit_status"] = 422
    files = FakeFiles()
    generate = video_tools.build(context(files))["GenerateVideo"].handler

    result = await generate(project="Campana", prompt="p", output_path="a.mp4")

    assert result == "Making the video failed: fal refused the request: nope"
    assert files.written == {}


async def test_a_job_that_runs_too_long_is_abandoned(fal, monkeypatch):
    fal.state["polls"] = 10
    monkeypatch.setattr(video_config, "TIMEOUT_SECONDS", 0)
    files = FakeFiles()
    generate = video_tools.build(context(files))["GenerateVideo"].handler

    result = await generate(project="Campana", prompt="p", output_path="a.mp4")

    assert "abandoned" in result and files.written == {}


def test_without_a_fal_key_there_are_no_video_tools():
    from src.assistants.catalog import unavailable

    without = context(FakeFiles(), credentials={})
    assert not video_tools.available(without)
    assert any("video generation" in line for line in unavailable(without))


def test_video_tools_always_ask_offer_only_fitting_models_and_reach_background_workers():
    built = video_tools.build(context(FakeFiles()))

    assert all(tool.always_ask for tool in built.values())
    assert built["EditVideo"].choices == {"model": ("kling-4", "kling-omni")}
    assert "kling-omni" not in built["GenerateVideo"].choices["model"]
    assert {"GenerateVideo", "AnimateImage", "EditVideo"} <= background_config.TOOLS


async def test_an_image_approval_never_lets_a_video_through():
    gate = AllowanceGate(
        frozenset({"GenerateImages", "GenerateVideo"}),
        Allowance(remaining=10, args={"model": images_config.SUNBURST}),
        lambda request: images_config.images_in(request.call.name, request.call.args),
        covers=images_config.TOOLS,
    )
    image = ClientRequest(call=ToolCall(id="i", name="GenerateImages", args={"images": [{}]}), requires_approval=True)
    video = ClientRequest(call=ToolCall(id="v", name="GenerateVideo", args={}), requires_approval=True)

    assert (await gate.decide([image]))[0].approved
    with pytest.raises(ClientActionRequired) as stopped:
        await gate.decide([video])
    assert [r.call.id for r in stopped.value.requests] == ["v"]
