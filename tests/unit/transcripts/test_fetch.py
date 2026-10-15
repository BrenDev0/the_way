from pathlib import Path

import pytest

from src.transcripts import fetch


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "youtube.com"),
        ("https://youtu.be/jNQXAC9IVRw", "youtu.be"),
        ("https://www.tiktok.com/@marca/video/123", "tiktok.com"),
        ("https://www.instagram.com/reel/abc/", "instagram.com"),
        # anywhere else is refused: the server would fetch whatever it was handed
        ("http://localhost:5432/", None),
        ("http://169.254.169.254/latest/meta-data/", None),
        ("https://youtube.com.evil.example/watch?v=x", None),
        ("file:///etc/passwd", None),
        ("project:Borradores/audio.mp3", None),
    ],
)
def test_only_the_listed_platforms_are_fetched_from(url, platform):
    assert fetch.platform_of(url) == platform


@pytest.mark.parametrize(
    ("url", "video"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=3", "jNQXAC9IVRw"),
        ("https://youtu.be/jNQXAC9IVRw?si=x", "jNQXAC9IVRw"),
        ("https://m.youtube.com/shorts/jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://www.youtube.com/channel/UC123", None),
        ("https://www.tiktok.com/@marca/video/123", None),
    ],
)
def test_a_youtube_video_is_known_by_its_id(url, video):
    assert fetch.youtube_id(url) == video


async def test_youtube_captions_come_first_and_nothing_is_downloaded(monkeypatch):
    async def captions(video_id, language):
        return fetch.Transcript(text="hola", title="", how="YouTube's captions (es)")

    def download(url, folder):
        raise AssertionError("nothing should be downloaded")

    monkeypatch.setattr(fetch, "captions", captions)
    monkeypatch.setattr(fetch, "_download", download)

    transcript = await fetch.from_link("https://youtu.be/jNQXAC9IVRw", None, None)

    assert transcript.text == "hola"


async def test_without_captions_the_audio_is_transcribed(monkeypatch, tmp_path):
    async def captions(video_id, language):
        raise fetch.Unavailable("the video has no captions")

    def download(url, folder):
        path = Path(folder) / "audio.webm"
        path.write_bytes(b"audio")
        return path, "Me at the zoo"

    async def transcribe(data, filename, api_key, language):
        assert (data, filename, api_key) == (b"audio", "audio.webm", "sk-test")
        return "All right, so here we are"

    monkeypatch.setattr(fetch, "captions", captions)
    monkeypatch.setattr(fetch, "_download", download)
    monkeypatch.setattr(fetch, "transcribe", transcribe)

    transcript = await fetch.from_link("https://youtu.be/jNQXAC9IVRw", "sk-test", None)

    assert transcript.text == "All right, so here we are"
    assert transcript.title == "Me at the zoo"


async def test_without_captions_or_a_key_it_says_why(monkeypatch):
    async def captions(video_id, language):
        raise fetch.Unavailable("YouTube refused this server's request for the captions")

    monkeypatch.setattr(fetch, "captions", captions)

    with pytest.raises(fetch.Unavailable) as raised:
        await fetch.from_link("https://youtu.be/jNQXAC9IVRw", None, None)

    assert "refused this server" in str(raised.value)
    assert "needs an OpenAI key" in str(raised.value)


async def test_audio_past_the_limit_is_refused_before_it_is_sent():
    with pytest.raises(fetch.Unavailable, match="over the 25 MB limit"):
        await fetch.transcribe(b"x" * (fetch.config.MAX_AUDIO_BYTES + 1), "a.mp3", "sk-test", None)
