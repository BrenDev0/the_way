"""Exact text on a finished clip: a video model cannot spell, so the words are drawn here
(with media.image_ops.add_text) and laid over the clip with ffmpeg."""

import asyncio
import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.media import image_ops

from . import config


class OverlayError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    text: str
    start: float = 0.0
    end: float | None = None
    position: str = "bottom"


@dataclass(frozen=True)
class Style:
    size: int | None = None
    color: str = "white"
    font: str = "sans-bold"
    box: str | None = None
    box_opacity: float = 0.6
    margin: int | None = None
    max_width: float = 0.9
    fade: float = 0.25


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    seconds: float


async def _exec(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise OverlayError(f"{args[0]} is not installed on the server, so text cannot be added to a video") from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise OverlayError(f"adding the text took longer than {int(timeout)} seconds; try a shorter clip") from exc
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, out, err


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(float(side["rotation"]))
    return int(float((stream.get("tags") or {}).get("rotate", 0) or 0))


async def probe(path: Path) -> VideoInfo:
    code, out, err = await _exec(
        [config.FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        config.PROBE_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise OverlayError(f"that file could not be read as a video: {err.decode(errors='replace').strip()[-200:]}")
    try:
        found = json.loads(out)
        stream = next(s for s in found["streams"] if s.get("codec_type") == "video")
        width, height = int(stream["width"]), int(stream["height"])
        seconds = float(found["format"]["duration"])
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise OverlayError("that file has no video to put text on") from exc
    # ffmpeg applies a phone clip's rotation tag, so the frame is the other way round
    if abs(_rotation(stream)) % 180 == 90:
        width, height = height, width
    return VideoInfo(width, height, seconds)


def _card_picture(info: VideoInfo, card: Card, style: Style) -> bytes:
    canvas = io.BytesIO()
    Image.new("RGBA", (info.width, info.height), (0, 0, 0, 0)).save(canvas, "PNG")
    drawn = image_ops.add_text(
        canvas.getvalue(), card.text, position=card.position, size=style.size, color=style.color,
        font=style.font, box=style.box, box_opacity=style.box_opacity, margin=style.margin,
        max_width=style.max_width,
    )
    out = io.BytesIO()
    drawn.save(out, "PNG")
    return out.getvalue()


def command(source: Path, pictures: list[Path], timings: list[tuple[float, float]], fade: float, target: Path) -> list[str]:
    args = [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    for picture in pictures:
        args += ["-loop", "1", "-i", str(picture)]

    steps: list[str] = []
    below = "0:v"
    for index, (start, end) in enumerate(timings, start=1):
        length = min(fade, (end - start) / 2)
        shape = "format=rgba"
        if length > 0:
            shape += (
                f",fade=t=in:st={start:.3f}:d={length:.3f}:alpha=1"
                f",fade=t=out:st={end - length:.3f}:d={length:.3f}:alpha=1"
            )
        steps.append(f"[{index}:v]{shape}[card{index}]")
        steps.append(
            f"[{below}][card{index}]overlay=0:0:shortest=1:enable='between(t,{start:.3f},{end:.3f})'[over{index}]"
        )
        below = f"over{index}"

    return [
        *args, "-filter_complex", ";".join(steps), "-map", f"[{below}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(target),
    ]


def _timings(cards: list[Card], info: VideoInfo) -> list[tuple[float, float]]:
    timings = []
    for number, card in enumerate(cards, start=1):
        if card.start >= info.seconds:
            raise OverlayError(
                f"text {number} starts at {card.start:g}s but the clip is only {info.seconds:.1f}s long"
            )
        end = min(card.end if card.end is not None else info.seconds, info.seconds)
        if end <= card.start:
            raise OverlayError(f"text {number} must end after it starts ({card.start:g}s)")
        timings.append((card.start, end))
    return timings


async def burn_text(data: bytes, cards: list[Card], style: Style) -> tuple[bytes, VideoInfo]:
    with tempfile.TemporaryDirectory(prefix="video-text-") as folder:
        root = Path(folder)
        source, target = root / "source", root / "result.mp4"
        source.write_bytes(data)
        info = await probe(source)
        if max(info.width, info.height) > config.MAX_TEXT_VIDEO_SIDE:
            raise OverlayError(
                f"the clip is {info.width}x{info.height}; text is added up to {config.MAX_TEXT_VIDEO_SIDE}px "
                "on its longer side"
            )
        timings = _timings(cards, info)

        pictures = []
        for number, card in enumerate(cards, start=1):
            picture = root / f"card{number}.png"
            picture.write_bytes(await asyncio.to_thread(_card_picture, info, card, style))
            pictures.append(picture)

        code, _, err = await _exec(command(source, pictures, timings, style.fade, target), config.TEXT_TIMEOUT_SECONDS)
        if code != 0 or not target.exists():
            raise OverlayError(f"ffmpeg could not add the text: {err.decode(errors='replace').strip()[-300:]}")
        return target.read_bytes(), info
