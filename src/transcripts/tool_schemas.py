from pydantic import BaseModel, Field


class TranscribeMedia(BaseModel):
    """Get the transcript of a video or a recording: a link to a post on YouTube, TikTok,
    Instagram, Facebook, Vimeo, X, LinkedIn, Twitch, Dailymotion or SoundCloud, or an audio
    or video file in one of the user's projects.

    A YouTube video's own captions are read first (free, no download). Otherwise the audio
    is downloaded and transcribed with the user's OpenAI key. The transcript is saved in
    the workspace and its text returned. Use it instead of asking the user to paste a
    transcript; ask them only when this says it could not get one."""

    source: str = Field(
        description="The link to the post (https://...), or a file as project:<project>/<path>"
    )
    language: str | None = Field(
        default=None,
        description="Optional. The language spoken, as a code ('es', 'en'), when known. "
        "Picks the right captions and helps the transcription.",
    )
