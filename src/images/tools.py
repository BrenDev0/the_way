"""Image generation and editing with OpenAI's GPT Image 2.5, saved into the user's projects.

Every call is approved by the user -- in a background task too, which suspends until they
answer (Tool.always_ask) -- and whoever approves picks the model (Tool.choices). The calls
run on the user's own OpenAI key.
"""

import asyncio
import base64
import io
from pathlib import PurePosixPath
from typing import Any

import openai
from openai import AsyncOpenAI

from src.api_keys.domain import Provider
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects.files import ProjectFiles

from . import config
from .tool_schemas import EditImage, GenerateImages

NO_KEY = (
    "Image generation needs an OpenAI key, and none has been issued to this user. Tell them "
    "an owner or admin can issue one; do not try again."
)

CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
LABELS = {config.FLARE: "Flare", config.SUNBURST: "Sunburst"}


def available(context: ToolContext) -> bool:
    return str(Provider.OPENAI) in context.credentials


def _option(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    return value if value in allowed else fallback


def _format_of(path: str, requested: Any) -> str:
    suffix = PurePosixPath(path).suffix.lower().lstrip(".")
    suffix = "jpeg" if suffix == "jpg" else suffix
    return _option(requested, config.FORMATS, suffix if suffix in config.FORMATS else "png")


def _describe_generate(project: str, images: list[dict[str, Any]], model: str = config.DEFAULT_MODEL) -> str:
    count = len(images)
    paths = ", ".join(str(image.get("output_path", "?")) for image in images)
    return f"generate {count} image{'' if count == 1 else 's'} into {project}: {paths}"


def _preview_generate(project: str, images: list[dict[str, Any]], model: str = config.DEFAULT_MODEL) -> str:
    lines = []
    for number, image in enumerate(images, 1):
        lines.append(
            f"{number}. {image.get('output_path', '?')} -- {image.get('size', 'auto')}, "
            f"quality {image.get('quality', 'auto')}"
            + (", transparent" if image.get("background") == "transparent" else "")
        )
        lines.append(f"   {image.get('prompt', '')}")
    return "\n".join(lines)


def _describe_edit(project: str, source_paths: list[str], output_paths: list[str], **_: Any) -> str:
    return (
        f"edit {', '.join(source_paths)} into {len(output_paths)} image"
        f"{'' if len(output_paths) == 1 else 's'} in {project}"
    )


def _preview_edit(project: str, source_paths: list[str], prompt: str, output_paths: list[str], **_: Any) -> str:
    return f"From: {', '.join(source_paths)}\nTo: {', '.join(output_paths)}\n\n{prompt}"


def build(context: ToolContext) -> dict[str, Tool]:
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )
    credential = context.credentials.get(str(Provider.OPENAI))

    def client() -> AsyncOpenAI:
        assert credential is not None
        return AsyncOpenAI(api_key=credential.secret, timeout=config.REQUEST_TIMEOUT_SECONDS)

    async def save(project_name: str, path: str, data: str, image_format: str) -> str:
        target = await files.project(project_name)
        saved = await files.write(
            target, path, base64.b64decode(data), overwrite=True,
            content_type=CONTENT_TYPES[image_format],
        )
        return f"{target.name}/{path.strip('/')} ({saved.size_bytes:,} bytes)"

    async def generate_images(
        project: str, images: list[dict[str, Any]], model: str = config.DEFAULT_MODEL
    ) -> str:
        if credential is None:
            return NO_KEY
        model = _option(model, config.MODELS, config.DEFAULT_MODEL)
        await files.project(project)  # a wrong name fails before anything is paid for

        async with client() as api:

            async def one(image: dict[str, Any]) -> str:
                path = str(image.get("output_path", "")).strip("/")
                image_format = _format_of(path, image.get("output_format"))
                try:
                    result = await api.images.generate(  # type: ignore[call-overload]
                        model=model,
                        prompt=str(image.get("prompt", "")),
                        size=_option(image.get("size"), config.SIZES, "auto"),
                        quality=_option(image.get("quality"), config.QUALITIES, "auto"),
                        background=_option(image.get("background"), config.BACKGROUNDS, "auto"),
                        output_format=image_format,
                        n=1,
                    )
                    data = result.data[0].b64_json if result.data else None
                    if not data:
                        return f"- {path}: FAILED -- no image came back"
                    return f"- saved {await save(project, path, data, image_format)}"
                except openai.APIError as exc:
                    return f"- {path}: FAILED -- {_reason(exc)}"

            lines = await asyncio.gather(*(one(image) for image in images))
        return f"Generated with {LABELS[model]} ({model}):\n" + "\n".join(lines)

    async def edit_image(
        project: str,
        source_paths: list[str],
        prompt: str,
        output_paths: list[str],
        mask_path: str | None = None,
        size: str = "auto",
        quality: str = "auto",
        background: str = "auto",
        model: str = config.DEFAULT_MODEL,
    ) -> str:
        if credential is None:
            return NO_KEY
        model = _option(model, config.MODELS, config.DEFAULT_MODEL)
        target = await files.project(project)

        async def load(path: str) -> io.BytesIO:
            _, data = await files.read_bytes(target, path, limit=config.MAX_REFERENCE_BYTES)
            buffer = io.BytesIO(data)
            # the API picks its decoder off the filename
            buffer.name = PurePosixPath(path).name
            return buffer

        sources = [await load(path) for path in source_paths[: config.MAX_REFERENCE_IMAGES]]
        mask = await load(mask_path) if mask_path else None
        image_format = _format_of(output_paths[0], None)

        async with client() as api:
            try:
                result = await api.images.edit(  # type: ignore[call-overload]
                    model=model,
                    image=sources,
                    prompt=prompt,
                    n=len(output_paths),
                    size=_option(size, config.SIZES, "auto"),
                    quality=_option(quality, config.QUALITIES, "auto"),
                    background=_option(background, config.BACKGROUNDS, "auto"),
                    output_format=image_format,
                    **({"mask": mask} if mask else {}),
                )
            except openai.APIError as exc:
                return f"Editing failed: {_reason(exc)}"

        lines = []
        for path, image in zip(output_paths, result.data or [], strict=False):
            if image.b64_json:
                lines.append(f"- saved {await save(project, path.strip('/'), image.b64_json, image_format)}")
        missing = len(output_paths) - len(lines)
        if missing:
            lines.append(f"- {missing} of the requested images did not come back")
        return f"Edited with {LABELS[model]} ({model}):\n" + "\n".join(lines)

    choices = {"model": config.MODELS}
    return {
        GenerateImages.__name__: Tool(
            schema=GenerateImages,
            handler=generate_images,
            requires_approval=True,
            always_ask=True,
            choices=choices,
            describe=_describe_generate,
            preview=_preview_generate,
        ),
        EditImage.__name__: Tool(
            schema=EditImage,
            handler=edit_image,
            requires_approval=True,
            always_ask=True,
            choices=choices,
            describe=_describe_edit,
            preview=_preview_edit,
        ),
    }


def _reason(exc: openai.APIError) -> str:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return "the OpenAI key was rejected -- tell the user an admin needs to issue a new one"
    if isinstance(exc, openai.BadRequestError):
        # usually the content policy, or a prompt the model could not use; the model can rephrase
        return f"OpenAI refused the request: {exc.message}"
    if isinstance(exc, openai.RateLimitError):
        return "OpenAI's rate limit or the account's quota was hit"
    return f"{type(exc).__name__}: {exc.message}"
