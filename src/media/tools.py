"""Exact edits to PDFs and images in the user's projects -- the tools a person would reach
for in a PDF editor or an image editor, done in code. Nothing here invents content: for
that there is EditImage (AI).

Every edit writes a new file unless told otherwise, so the original is never lost by
accident; reports name the saved file the way the app's file chips read it ("Saved P/x").
"""

import asyncio
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any, TypeVar

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from pypdf.errors import PdfReadError

from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects.domain import Project, ProjectFile
from src.projects.files import ProjectFiles

from . import config, image_ops, pdf_ops
from .pages import PageSpecError
from .tool_schemas import (
    AddTextToImage,
    EditPdfPages,
    ImagesToPdf,
    InspectImage,
    MergePdfs,
    OverlayImage,
    PdfToImages,
    ReadPdf,
    TransformImage,
)

T = TypeVar("T")

# What a person can fix by asking differently: shown to the model, not raised.
EXPECTED = (ValueError, PageSpecError, PdfReadError, UnidentifiedImageError, OSError, Image.DecompressionBombError)


class Refused(Exception):
    """Said to the model as the tool's answer: what to do differently."""


def _suffix(path: str) -> str:
    return PurePosixPath(path).suffix.lower().lstrip(".")


def _edited(path: str, extension: str | None = None) -> str:
    source = PurePosixPath(path.strip("/"))
    return str(source.with_name(f"{source.stem}-editado.{extension or source.suffix.lstrip('.') or 'png'}"))


def build(context: ToolContext) -> dict[str, Tool]:
    files = ProjectFiles(context.session, context.organization_id, context.user_id, context.bucket_store)

    async def load(target: Project, path: str) -> bytes:
        _, data = await files.read_bytes(target, path, limit=config.MAX_INPUT_BYTES)
        return data

    async def free(target: Project, path: str, overwrite: bool) -> None:
        if not overwrite and isinstance(await files.entry(target, path), ProjectFile):
            raise Refused(
                f"{target.name}/{path} already exists. Pick another output_path, or pass "
                "overwrite=true if the user wants it replaced."
            )

    async def save(target: Project, path: str, data: bytes, note: str = "") -> str:
        saved = await files.write(
            target, path, data, overwrite=True,
            content_type=config.CONTENT_TYPES.get(_suffix(path), "application/octet-stream"),
        )
        return f"Saved {target.name}/{path.strip('/')} ({', '.join(filter(None, [note, f'{saved.size_bytes:,} bytes']))})"

    async def cpu(work: Callable[[], T]) -> T:
        return await asyncio.to_thread(work)

    def guarded(handler: Callable[..., Any]) -> Callable[..., Any]:
        async def run(**kwargs: Any) -> str:
            try:
                return await handler(**kwargs)
            except Refused as exc:
                return str(exc)
            except EXPECTED as exc:
                return f"Could not do that: {exc}"

        run.__name__ = handler.__name__
        return run

    def image_out(path: str, output_path: str | None, image_format: str | None) -> tuple[str, str]:
        """Where an edited image goes and in what format: the format asked for, else the
        output path's extension, else the source's."""
        fmt = image_format or (_suffix(output_path) if output_path else "") or _suffix(path)
        fmt = "jpeg" if fmt == "jpg" else fmt if fmt in config.IMAGE_FORMATS else "png"
        destination = (output_path or _edited(path, "jpg" if fmt == "jpeg" else fmt)).strip("/")
        return destination, fmt

    # --- PDFs ---------------------------------------------------------------------------

    async def read_pdf(project: str, path: str, pages: str | None = None) -> str:
        target = await files.project(project)
        data = await load(target, path)
        summary = await cpu(lambda: pdf_ops.read(data, pages))
        width, height = summary.sizes[0] if summary.sizes else (0, 0)
        sizes = {(round(w), round(h)) for w, h in summary.sizes}
        header = [
            f"{target.name}/{path}: {summary.pages} page{'' if summary.pages == 1 else 's'}, "
            f"{round(width)}x{round(height)} pt ({round(width / 72 * 25.4)}x{round(height / 72 * 25.4)} mm)"
            + (" -- pages differ in size" if len(sizes) > 1 else ""),
        ]
        if summary.metadata:
            header.append("Metadata: " + "; ".join(f"{k}: {v}" for k, v in summary.metadata.items()))
        return "\n".join(header) + "\n\n" + summary.text

    async def edit_pdf_pages(
        project: str, path: str, output_path: str | None = None, keep: str | None = None,
        remove: str | None = None, rotate: int = 0, rotate_pages: str | None = None, overwrite: bool = False,
    ) -> str:
        if not (keep or remove or rotate):
            raise Refused("Say what to change: keep (pages and order), remove, or rotate.")
        target = await files.project(project)
        destination = (output_path or _edited(path, "pdf")).strip("/")
        await free(target, destination, overwrite)
        data = await load(target, path)
        result, count = await cpu(lambda: pdf_ops.rearrange(data, keep, remove, rotate, rotate_pages))
        return await save(target, destination, result, f"{count} page{'' if count == 1 else 's'}")

    async def merge_pdfs(project: str, paths: list[str], output_path: str, overwrite: bool = False) -> str:
        target = await files.project(project)
        await free(target, output_path.strip("/"), overwrite)
        documents = [await load(target, path) for path in paths]
        result, count = await cpu(lambda: pdf_ops.merge(documents))
        return await save(target, output_path, result, f"{len(paths)} files, {count} pages")

    async def pdf_to_images(
        project: str, path: str, pages: str | None = None, output_folder: str | None = None,
        dpi: int = config.DEFAULT_RENDER_DPI, image_format: str = "png",
    ) -> str:
        target = await files.project(project)
        data = await load(target, path)
        rendered = await cpu(lambda: pdf_ops.to_images(data, pages, dpi, image_format))
        source = PurePosixPath(path.strip("/"))
        folder = (output_folder or str(source.with_name(source.stem))).strip("/")
        extension = "jpg" if image_format == "jpeg" else image_format
        lines = []
        for number, image in rendered:
            saved = await save(target, f"{folder}/{source.stem}-p{number}.{extension}", image, f"page {number}")
            lines.append(f"- {saved.replace('Saved', 'saved', 1)}")
        return f"Rendered {len(rendered)} page{'' if len(rendered) == 1 else 's'} at {dpi} dpi:\n" + "\n".join(lines)

    async def images_to_pdf(
        project: str, paths: list[str], output_path: str, page_size: str = "fit",
        margin_mm: float = 10, overwrite: bool = False,
    ) -> str:
        target = await files.project(project)
        await free(target, output_path.strip("/"), overwrite)
        images = [await load(target, path) for path in paths]
        result = await cpu(lambda: pdf_ops.from_images(images, page_size, margin_mm / 25.4 * 72))
        return await save(target, output_path, result, f"{len(paths)} page{'' if len(paths) == 1 else 's'}, {page_size}")

    # --- images -------------------------------------------------------------------------

    async def inspect_image(project: str, path: str) -> str:
        target = await files.project(project)
        data = await load(target, path)
        summary = await cpu(lambda: image_ops.inspect(data))
        return (
            f"{target.name}/{path}: {summary.width}x{summary.height} px, {summary.format}, "
            f"{'with' if summary.transparent else 'no'} transparency"
        )

    async def transform_image(
        project: str, path: str, output_path: str | None = None, crop: dict[str, int] | None = None,
        crop_aspect: str | None = None, rotate: float = 0, flip: str | None = None,
        width: int | None = None, height: int | None = None, fit: str = "contain",
        grayscale: bool = False, padding: int = 0, background: str | None = None,
        image_format: str | None = None, quality: int = 90, overwrite: bool = False,
    ) -> str:
        target = await files.project(project)
        destination, fmt = image_out(path, output_path, image_format)
        await free(target, destination, overwrite)
        data = await load(target, path)
        box = (crop["left"], crop["top"], crop["width"], crop["height"]) if crop else None

        def work() -> tuple[bytes, tuple[int, int]]:
            image = image_ops.transform(
                data, crop=box, crop_aspect=crop_aspect, rotate=rotate, flip=flip, width=width,
                height=height, fit=fit, grayscale=grayscale, padding=padding, background=background,
            )
            return image_ops.encode(image, fmt, quality), image.size

        result, (out_width, out_height) = await cpu(work)
        return await save(target, destination, result, f"{out_width}x{out_height} px, {fmt}")

    async def add_text_to_image(
        project: str, path: str, text: str, output_path: str | None = None, position: str = "bottom",
        size: int | None = None, color: str = "white", font: str = "sans-bold", box: str | None = None,
        box_opacity: float = 0.6, margin: int | None = None, max_width: float = 0.9, overwrite: bool = False,
    ) -> str:
        target = await files.project(project)
        destination, fmt = image_out(path, output_path, None)
        await free(target, destination, overwrite)
        data = await load(target, path)
        image = await cpu(lambda: image_ops.add_text(
            data, text, position=position, size=size, color=color, font=font, box=box,
            box_opacity=box_opacity, margin=margin, max_width=max_width,
        ))
        result = await cpu(lambda: image_ops.encode(image, fmt))
        return await save(target, destination, result, f"{image.width}x{image.height} px")

    async def overlay_image(
        project: str, path: str, overlay_path: str, output_path: str | None = None,
        position: str = "bottom-right", scale: float = 0.2, opacity: float = 1.0,
        margin: int | None = None, overwrite: bool = False,
    ) -> str:
        target = await files.project(project)
        destination, fmt = image_out(path, output_path, None)
        await free(target, destination, overwrite)
        base, top = await load(target, path), await load(target, overlay_path)
        image = await cpu(lambda: image_ops.overlay(base, top, position=position, scale=scale, opacity=opacity, margin=margin))
        result = await cpu(lambda: image_ops.encode(image, fmt))
        return await save(target, destination, result, f"{image.width}x{image.height} px")

    handlers: dict[type[BaseModel], Callable[..., Any]] = {
        ReadPdf: read_pdf,
        EditPdfPages: edit_pdf_pages,
        MergePdfs: merge_pdfs,
        PdfToImages: pdf_to_images,
        ImagesToPdf: images_to_pdf,
        InspectImage: inspect_image,
        TransformImage: transform_image,
        AddTextToImage: add_text_to_image,
        OverlayImage: overlay_image,
    }
    # They make new files and never delete, so nothing here needs approval -- the same line
    # WriteProjectFile draws. Replacing a file takes an explicit overwrite.
    return {schema.__name__: Tool(schema=schema, handler=guarded(handler)) for schema, handler in handlers.items()}
