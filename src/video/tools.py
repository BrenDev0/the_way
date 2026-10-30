"""Video generation and editing on fal (Seedance, Kling), saved into the user's projects.

Every call is approved by the user -- in a background task too, which suspends until they
answer (Tool.always_ask) -- and whoever approves picks the model (Tool.choices). Unlike
images, one approval never covers the next video. The calls run on the organization's fal
key, as jobs on fal's queue: submitted, polled until done, then downloaded.
"""

import asyncio
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from src.api_keys.domain import Provider
from src.assistants.context import ToolContext
from src.core.tools.domain import Tool

from . import config
from .tool_schemas import AnimateImage, EditVideo, GenerateVideo

NO_KEY = (
    "Video generation needs a fal key, and none has been set up for this organization. "
    "Tell them Xplorers sets keys up for their organization; do not try again."
)


class FalError(Exception):
    pass


def available(context: ToolContext) -> bool:
    return str(Provider.FAL) in context.credentials


def _option(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    return value if value in allowed else fallback


def _mp4(path: str) -> str:
    path = str(path).strip().strip("/")
    return path if path.lower().endswith(".mp4") else f"{PurePosixPath(path).with_suffix('')}.mp4"


def _seconds(model: config.VideoModel, seconds: Any) -> dict[str, Any]:
    if not isinstance(seconds, int):
        return {}
    clamped = min(max(seconds, model.min_seconds), model.max_seconds)
    return {"duration": clamped if model.seconds_as_int else str(clamped)}


def _label(model: str) -> str:
    return f"{config.MODELS_BY_KEY[model].label} ({model})"


def _describe_generate(project: str, output_path: str, model: str = config.DEFAULT_MODEL, **_: Any) -> str:
    return f"generate a video into {project}: {_mp4(output_path)}"


def _preview_generate(
    project: str, prompt: str, output_path: str, seconds: int | None = None,
    aspect_ratio: str = "16:9", **_: Any,
) -> str:
    length = f"{seconds}s" if seconds else "default length"
    return f"{_mp4(output_path)} -- {length}, {aspect_ratio}\n\n{prompt}"


def _describe_animate(project: str, image_path: str, output_path: str, **_: Any) -> str:
    return f"animate {image_path} into a video in {project}: {_mp4(output_path)}"


def _preview_animate(
    project: str, image_path: str, prompt: str, output_path: str,
    end_image_path: str | None = None, seconds: int | None = None, **_: Any,
) -> str:
    frames = f"From: {image_path}" + (f"\nEnding on: {end_image_path}" if end_image_path else "")
    length = f"{seconds}s" if seconds else "default length"
    return f"{frames}\nTo: {_mp4(output_path)} -- {length}\n\n{prompt}"


def _describe_edit(project: str, video_path: str, output_path: str, **_: Any) -> str:
    return f"edit the video {video_path} into {project}: {_mp4(output_path)}"


def _preview_edit(
    project: str, video_path: str, prompt: str, output_path: str,
    reference_image_paths: list[str] | None = None, **_: Any,
) -> str:
    references = f"\nReferences: {', '.join(reference_image_paths)}" if reference_image_paths else ""
    return f"From: {video_path}{references}\nTo: {_mp4(output_path)}\n\n{prompt}"


def build(context: ToolContext) -> dict[str, Tool]:
    files = context.files
    credential = context.credentials.get(str(Provider.FAL))
    headers = {"Authorization": f"Key {credential.secret}"} if credential else {}

    async def send(
        http: httpx.AsyncClient, method: str, url: str, body: dict | None = None, signed: bool = True
    ) -> httpx.Response:
        try:
            response = await http.request(method, url, json=body, headers=headers if signed else None)
        except httpx.HTTPError as exc:
            raise FalError(f"fal could not be reached: {exc}") from exc
        if response.is_error:
            raise FalError(_reason(response))
        return response

    async def upload(http: httpx.AsyncClient, name: str, data: bytes, content_type: str) -> str:
        """Puts a source file on fal's CDN; the endpoints take sources as URLs."""
        token = (await send(http, "POST", config.UPLOAD_TOKEN_URL, {})).json()
        try:
            stored = await http.post(
                f"{token['base_url'].rstrip('/')}/files/upload",
                content=data,
                headers={
                    "Authorization": f"{token['token_type']} {token['token']}",
                    "Content-Type": content_type,
                    # a header takes ASCII only, and names here are often Spanish
                    "X-Fal-File-Name": quote(name),
                },
            )
        except (httpx.HTTPError, KeyError) as exc:
            raise FalError(f"the source file could not be uploaded to fal: {exc}") from exc
        if stored.is_error:
            raise FalError(f"the source file could not be uploaded to fal: {_reason(stored)}")
        return str(stored.json()["access_url"])

    async def load(http: httpx.AsyncClient, target: Any, path: str, limit: int) -> str:
        # a source may be in another project (project:<name>/<path>); results stay in target
        source, inner = await files.source(target, path)
        found, data = await files.read_bytes(source, inner, limit=limit)
        return await upload(http, found.name, data, found.content_type)

    async def run(http: httpx.AsyncClient, endpoint: str, body: dict) -> bytes | str:
        """Submits the job, polls it until done, and downloads the clip. A str is the
        message when it ran out of time."""
        job = (await send(http, "POST", f"{config.QUEUE_URL}/{endpoint}", body)).json()
        status_url, response_url = job.get("status_url"), job.get("response_url")
        if not status_url or not response_url:
            raise FalError(f"fal did not start a job: {str(job)[:300]}")

        waited = 0.0
        while (await send(http, "GET", status_url)).json().get("status") != "COMPLETED":
            if waited >= config.TIMEOUT_SECONDS:
                return (
                    f"The video was still being made after {config.TIMEOUT_SECONDS // 60} minutes "
                    "and was abandoned. Tell the user; try a shorter clip or another model."
                )
            await asyncio.sleep(config.POLL_SECONDS)
            waited += config.POLL_SECONDS

        # a job that failed on fal's side answers here with its error
        result = (await send(http, "GET", response_url)).json()
        url = (result.get("video") or {}).get("url")
        if not url:
            raise FalError(f"no video came back: {str(result)[:300]}")
        return (await send(http, "GET", url, signed=False)).content

    async def make(project: str, output_path: str, model: str, endpoint_of: Any, inputs: Any) -> str:
        """Everything the three tools share: the project is found before anything is paid
        for, the sources go up, the job runs, and the clip is saved."""
        target = await files.project(project)
        path = _mp4(output_path)
        try:
            async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as http:
                body = await inputs(http, target)
                made = await run(http, endpoint_of(config.MODELS_BY_KEY[model]), body)
        except FalError as exc:
            return f"Making the video failed: {exc}"
        if isinstance(made, str):
            return made
        saved = await files.write(target, path, made, overwrite=True, content_type="video/mp4")
        return f"Made with {_label(model)}: saved {target.name}/{path} ({saved.size_bytes:,} bytes)"

    async def generate_video(
        project: str,
        prompt: str,
        output_path: str,
        seconds: int | None = None,
        aspect_ratio: str = "16:9",
        model: str = config.DEFAULT_MODEL,
    ) -> str:
        if credential is None:
            return NO_KEY
        model = _option(model, config.TEXT_MODELS, config.DEFAULT_MODEL)
        chosen = config.MODELS_BY_KEY[model]

        async def inputs(http: httpx.AsyncClient, target: Any) -> dict:
            ratio = {"aspect_ratio": aspect_ratio} if aspect_ratio in chosen.aspect_ratios else {}
            return {"prompt": prompt, **_seconds(chosen, seconds), **ratio}

        return await make(project, output_path, model, lambda m: m.text, inputs)

    async def animate_image(
        project: str,
        image_path: str,
        prompt: str,
        output_path: str,
        end_image_path: str | None = None,
        seconds: int | None = None,
        model: str = config.DEFAULT_MODEL,
    ) -> str:
        if credential is None:
            return NO_KEY
        model = _option(model, config.IMAGE_MODELS, config.DEFAULT_MODEL)
        chosen = config.MODELS_BY_KEY[model]

        async def inputs(http: httpx.AsyncClient, target: Any) -> dict:
            body = {
                "prompt": prompt,
                chosen.image_field: await load(http, target, image_path, config.MAX_IMAGE_BYTES),
                **_seconds(chosen, seconds),
            }
            if end_image_path:
                body["end_image_url"] = await load(http, target, end_image_path, config.MAX_IMAGE_BYTES)
            return body

        return await make(project, output_path, model, lambda m: m.image, inputs)

    async def edit_video(
        project: str,
        video_path: str,
        prompt: str,
        output_path: str,
        reference_image_paths: list[str] | None = None,
        model: str = config.DEFAULT_MODEL,
    ) -> str:
        if credential is None:
            return NO_KEY
        model = _option(model, config.EDIT_MODELS, config.DEFAULT_MODEL)

        async def inputs(http: httpx.AsyncClient, target: Any) -> dict:
            body: dict[str, Any] = {
                "prompt": prompt,
                "video_url": await load(http, target, video_path, config.MAX_VIDEO_BYTES),
            }
            if reference_image_paths:
                body["image_urls"] = [
                    await load(http, target, path, config.MAX_IMAGE_BYTES) for path in reference_image_paths[:4]
                ]
            return body

        return await make(project, output_path, model, lambda m: m.edit, inputs)

    return {
        GenerateVideo.__name__: Tool(
            schema=GenerateVideo,
            handler=generate_video,
            requires_approval=True,
            always_ask=True,
            choices={"model": config.TEXT_MODELS},
            describe=_describe_generate,
            preview=_preview_generate,
        ),
        AnimateImage.__name__: Tool(
            schema=AnimateImage,
            handler=animate_image,
            requires_approval=True,
            always_ask=True,
            choices={"model": config.IMAGE_MODELS},
            describe=_describe_animate,
            preview=_preview_animate,
        ),
        EditVideo.__name__: Tool(
            schema=EditVideo,
            handler=edit_video,
            requires_approval=True,
            always_ask=True,
            choices={"model": config.EDIT_MODELS},
            describe=_describe_edit,
            preview=_preview_edit,
        ),
    }


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = str(body.get("detail", body) if isinstance(body, dict) else response.text)[:300]
    if response.status_code in (401, 403):
        return f"the fal key was rejected or the account is locked ({detail}) -- tell the user an admin needs to check it"
    if response.status_code == 422:
        # usually the content policy, or an input the model could not use; the model can rephrase
        return f"fal refused the request: {detail}"
    if response.status_code == 429:
        return "fal's rate limit or the account's balance was hit"
    return f"fal answered {response.status_code}: {detail}"
