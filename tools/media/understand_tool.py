"""``media_understand`` — read what arrived: audio, video, or an image.

Attachments are how people actually send information. A voice note, a
screen recording, a photo of a whiteboard — an agent that can only read
text treats all of those as "the user sent a file" and asks them to type
it out instead, which is the opposite of assistance.

Audio and video go through the shared speech engine (video has its audio
extracted first with ffmpeg). Images go to whichever vision model the
router already has configured, so this adds no new provider surface.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_AUDIO_SUFFIXES = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".aiff", ".wma"}
)
_VIDEO_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"}
)
_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".heic"}
)


class MediaUnderstandTool(BaseTool):
    """Transcribe or describe an audio, video, or image file."""

    def __init__(self) -> None:
        self._speech: Any = None  # SpeechEngine, injected
        self._router: Any = None  # LLM router, injected
        self._config: Any = None  # injected

    @property
    def name(self) -> str:
        return "media_understand"

    @property
    def group(self) -> str:
        return "media"

    @property
    def description(self) -> str:
        return (
            "Understand a media file the user sent: transcribe audio or video "
            "(voice notes, recordings, meetings) or describe an image "
            "(screenshots, photos, whiteboards). Use this whenever a file "
            "arrives that is not text — do not ask the user to type out what "
            "they already sent."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the audio, video, or image file.",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language hint for transcription, e.g. 'cs'.",
                },
                "question": {
                    "type": "string",
                    "description": (
                        "For images: what to look for. Defaults to a general "
                        "description."
                    ),
                },
            },
            "required": ["path"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        path = Path(str(params.get("path", "")).strip()).expanduser()
        if not path.exists():
            return ToolResult(success=False, error=f"No such file: {path}")

        suffix = path.suffix.lower()
        try:
            if suffix in _IMAGE_SUFFIXES:
                return await self._describe_image(path, params)
            if suffix in _VIDEO_SUFFIXES:
                return await self._transcribe_video(path, params)
            if suffix in _AUDIO_SUFFIXES:
                return await self._transcribe_audio(path, params)
        except Exception as exc:
            logger.error("media_understand failed on %s: %s", path.name, exc)
            return ToolResult(success=False, error=f"Could not read {path.name}: {exc}")

        return ToolResult(
            success=False,
            error=(
                f"Unsupported file type {suffix!r}. Handles audio "
                f"({', '.join(sorted(_AUDIO_SUFFIXES))}), video, and images."
            ),
        )

    # ── handlers ────────────────────────────────────────────────────

    async def _transcribe_audio(self, path: Path, params: dict[str, Any]) -> ToolResult:
        if self._speech is None:
            return ToolResult(
                success=False,
                error=(
                    "Speech support is not configured. Set the voice_channel "
                    "section in config.yaml (an OpenAI key or a local whisper "
                    "binary is enough)."
                ),
            )
        transcript = await self._speech.transcribe(
            path, language=str(params.get("language", "") or "")
        )
        if not transcript:
            return ToolResult(
                success=True,
                data={"kind": "audio", "transcript": "", "note": "No speech detected."},
            )
        return ToolResult(
            success=True,
            data={
                "kind": "audio",
                "source": path.name,
                "transcript": transcript,
                "characters": len(transcript),
            },
        )

    async def _transcribe_video(self, path: Path, params: dict[str, Any]) -> ToolResult:
        if not shutil.which("ffmpeg"):
            return ToolResult(
                success=False,
                error=(
                    "Transcribing video needs ffmpeg on PATH to extract the "
                    "audio track. Install ffmpeg, or send the audio directly."
                ),
            )
        audio_path = Path(tempfile.mkstemp(suffix=".wav")[1])
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                str(audio_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    error=(
                        "ffmpeg could not extract audio: "
                        f"{stderr.decode('utf-8', 'replace')[-300:]}"
                    ),
                )
            result = await self._transcribe_audio(audio_path, params)
            if result.success:
                result.data["kind"] = "video"
                result.data["source"] = path.name
            return result
        finally:
            audio_path.unlink(missing_ok=True)

    async def _describe_image(self, path: Path, params: dict[str, Any]) -> ToolResult:
        if self._router is None:
            return ToolResult(
                success=False, error="No LLM router available for image description."
            )
        import base64

        vision_model = getattr(
            getattr(self._config, "browser", None), "vision_model", ""
        )
        if not vision_model:
            return ToolResult(
                success=False,
                error=(
                    "No vision model configured. Set browser.vision_model in "
                    "config.yaml to describe images."
                ),
            )

        question = str(params.get("question", "") or "").strip() or (
            "Describe this image in detail. If it contains text, transcribe it "
            "exactly. If it is a screenshot or diagram, explain what it shows."
        )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

        response = await self._router.complete(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
            task_type="vision",
        )
        description = _text_of(response)
        return ToolResult(
            success=True,
            data={
                "kind": "image",
                "source": path.name,
                "description": description,
            },
        )


def _text_of(response: Any) -> str:
    """Pull the text out of whatever shape the router returned."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    try:
        return str(response.choices[0].message.content)
    except Exception:
        return str(response)
