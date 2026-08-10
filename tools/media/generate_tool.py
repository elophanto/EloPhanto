"""``video_generate`` and ``music_generate`` — create media from a prompt.

Both follow the pattern the existing Replicate image plugin established:
a thin provider seam, an async job the agent polls, and a file on disk at
the end. Generation is slow (tens of seconds to minutes) and metered, so
the tools are honest about cost and never silently retry — a retried
video generation is a second bill.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_REPLICATE_API = "https://api.replicate.com/v1/predictions"
_POLL_INTERVAL = 3.0
_MAX_POLLS = 200  # ~10 minutes


class _ReplicateMediaTool(BaseTool):
    """Shared Replicate prediction plumbing for the two generators."""

    default_model: str = ""
    output_suffix: str = ".mp4"

    def __init__(self) -> None:
        self._vault: Any = None  # injected
        self._config: Any = None  # injected

    def _api_token(self) -> str:
        if self._vault is None:
            return ""
        for key in ("replicate_api_token", "replicate", "REPLICATE_API_TOKEN"):
            value = self._vault.get(key)
            if isinstance(value, dict):
                value = value.get("token") or value.get("api_key")
            if value:
                return str(value)
        return ""

    async def _run_prediction(
        self, model: str, payload: dict[str, Any], timeout_polls: int = _MAX_POLLS
    ) -> tuple[bool, Any]:
        """Create a prediction and poll to completion.

        Returns ``(ok, output_or_error)``.
        """
        token = self._api_token()
        if not token:
            return False, (
                "No Replicate API token. Store one in the vault: "
                "`elophanto vault set replicate_api_token`."
            )
        try:
            import httpx
        except ImportError:  # pragma: no cover
            return False, "httpx is required for media generation."

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            create = await client.post(
                _REPLICATE_API,
                headers=headers,
                json={"version": model, "input": payload},
            )
            if create.status_code >= 400:
                return False, (
                    f"Replicate rejected the request ({create.status_code}): "
                    f"{create.text[:300]}"
                )
            prediction = create.json()
            poll_url = prediction.get("urls", {}).get("get", "")
            if not poll_url:
                return False, "Replicate returned no polling URL."

            for _ in range(timeout_polls):
                await asyncio.sleep(_POLL_INTERVAL)
                poll = await client.get(poll_url, headers=headers)
                if poll.status_code >= 400:
                    return False, f"Polling failed ({poll.status_code})."
                state = poll.json()
                status = state.get("status")
                if status == "succeeded":
                    return True, state.get("output")
                if status in ("failed", "canceled"):
                    return False, (
                        f"Generation {status}: {state.get('error') or 'no detail'}"
                    )
        return False, (
            f"Generation did not finish within "
            f"{int(timeout_polls * _POLL_INTERVAL / 60)} minutes. It may still "
            "be running at Replicate — do not simply retry, that bills twice."
        )

    async def _download(self, url: str, suffix: str) -> Path | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.get(url)
            if response.status_code >= 400:
                return None
            path = Path(tempfile.mkstemp(suffix=suffix)[1])
            path.write_bytes(response.content)
            return path
        except Exception as exc:
            logger.error("Downloading generated media failed: %s", exc)
            return None


class VideoGenerateTool(_ReplicateMediaTool):
    """Generate a short video from a text prompt (or an image)."""

    default_model = "minimax/video-01"
    output_suffix = ".mp4"

    @property
    def name(self) -> str:
        return "video_generate"

    @property
    def group(self) -> str:
        return "media"

    @property
    def description(self) -> str:
        return (
            "Generate a short video from a text prompt, optionally starting "
            "from an image. Takes 1-5 minutes and costs real money per "
            "generation, so confirm the prompt with the user first and never "
            "retry silently."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What the video should show.",
                },
                "image_url": {
                    "type": "string",
                    "description": "Optional first-frame image URL (image-to-video).",
                },
                "model": {
                    "type": "string",
                    "description": f"Replicate model version. Default {self.default_model!r}.",
                },
            },
            "required": ["prompt"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Metered spend on an external service — always confirm.
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        prompt = str(params.get("prompt", "") or "").strip()
        if not prompt:
            return ToolResult(success=False, error="`prompt` is required.")

        payload: dict[str, Any] = {"prompt": prompt}
        if params.get("image_url"):
            payload["first_frame_image"] = str(params["image_url"])

        ok, output = await self._run_prediction(
            str(params.get("model") or self.default_model), payload
        )
        if not ok:
            return ToolResult(success=False, error=str(output))

        url = output[0] if isinstance(output, list) and output else output
        path = await self._download(str(url), self.output_suffix)
        return ToolResult(
            success=True,
            data={
                "prompt": prompt,
                "url": str(url),
                "path": str(path) if path else "",
                "note": "Video generated. Costs were incurred for this call.",
            },
        )


class MusicGenerateTool(_ReplicateMediaTool):
    """Generate music or an audio bed from a text prompt."""

    default_model = "meta/musicgen"
    output_suffix = ".mp3"

    @property
    def name(self) -> str:
        return "music_generate"

    @property
    def group(self) -> str:
        return "media"

    @property
    def description(self) -> str:
        return (
            "Generate music or an audio bed from a text prompt (genre, mood, "
            "instrumentation, tempo). Metered per generation — confirm the "
            "prompt before spending."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Describe the music: genre, mood, instruments, tempo.",
                },
                "duration": {
                    "type": "integer",
                    "description": "Length in seconds (default 8, max 30).",
                },
                "model": {
                    "type": "string",
                    "description": f"Replicate model version. Default {self.default_model!r}.",
                },
            },
            "required": ["prompt"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        prompt = str(params.get("prompt", "") or "").strip()
        if not prompt:
            return ToolResult(success=False, error="`prompt` is required.")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "duration": max(1, min(int(params.get("duration") or 8), 30)),
        }
        ok, output = await self._run_prediction(
            str(params.get("model") or self.default_model), payload
        )
        if not ok:
            return ToolResult(success=False, error=str(output))

        url = output[0] if isinstance(output, list) and output else output
        path = await self._download(str(url), self.output_suffix)
        return ToolResult(
            success=True,
            data={
                "prompt": prompt,
                "url": str(url),
                "path": str(path) if path else "",
                "duration": payload["duration"],
            },
        )
