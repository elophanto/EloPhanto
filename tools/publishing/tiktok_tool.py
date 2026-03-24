"""tiktok_upload — Upload short videos to TikTok via browser bridge."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_TIKTOK_UPLOAD_URL = "https://www.tiktok.com/creator#/upload?scene=creator_center"
_MAX_CAPTION = 2200


class TikTokUploadTool(BaseTool):
    """Upload a short video to TikTok."""

    def __init__(self) -> None:
        self._browser_manager: Any = None
        self._db: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "tiktok_upload"

    @property
    def description(self) -> str:
        return (
            "Upload a short video to TikTok. Uses pre-authenticated Chrome "
            "profile — user must be logged into TikTok in Chrome. Returns "
            "the published video URL."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Local path to the video file (MP4).",
                },
                "caption": {
                    "type": "string",
                    "description": f"Video caption (max {_MAX_CAPTION} chars).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Hashtags (without #, will be auto-prefixed).",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["public", "friends", "private"],
                    "description": "Who can view (default: public).",
                },
            },
            "required": ["file_path", "caption"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def _log_publish(
        self,
        caption: str,
        file_path: str,
        platform_url: str,
        status: str,
        campaign_id: str = "",
    ) -> str:
        publish_id = f"pub_{uuid.uuid4().hex[:12]}"
        if not self._db:
            return publish_id
        now = datetime.now(UTC).isoformat()
        try:
            await self._db.execute_insert(
                "INSERT INTO publishing_log "
                "(publish_id, platform, content_type, title, local_path, "
                "platform_url, status, metadata_json, campaign_id, "
                "created_at, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (
                    publish_id,
                    "tiktok",
                    "video",
                    caption[:100],
                    file_path,
                    platform_url,
                    status,
                    campaign_id,
                    now,
                    now if status == "published" else None,
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to log publish: {e}")
        return publish_id

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._browser_manager:
            return ToolResult(success=False, error="Browser not available.")

        file_path = params["file_path"]
        caption = params["caption"]
        tags = params.get("tags", [])
        visibility = params.get("visibility", "public")

        if not os.path.isfile(file_path):
            return ToolResult(success=False, error=f"Video file not found: {file_path}")

        if len(caption) > _MAX_CAPTION:
            return ToolResult(
                success=False,
                error=f"Caption exceeds {_MAX_CAPTION} chars ({len(caption)}).",
            )

        # Append hashtags to caption
        if tags:
            hashtags = " ".join(f"#{t.lstrip('#')}" for t in tags)
            full_caption = f"{caption}\n\n{hashtags}"
        else:
            full_caption = caption

        try:
            # Step 1: Navigate to TikTok creator upload page
            await self._browser_manager.call_tool(
                "browser_navigate", {"url": _TIKTOK_UPLOAD_URL}
            )
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 4000}
            )

            # Step 2: Upload the video file
            page = await self._browser_manager.agent.getPage()
            file_input = await page.querySelector('input[type="file"]')
            if file_input:
                await file_input.setInputFiles(file_path)
            else:
                # Try clicking the upload area first
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": "Select file"}
                )
                await self._browser_manager.agent.uploadFileChooser([file_path])

            # Step 3: Wait for video to process
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 8000}
            )

            # Step 4: Fill in caption
            # TikTok's caption editor — find the editable area
            await self._browser_manager.call_tool(
                "browser_eval",
                {
                    "expression": (
                        "const editor = document.querySelector("
                        "'div[contenteditable=\"true\"]'"
                        ") || document.querySelector('.notranslate.public-DraftEditor-content');"
                        "if (editor) { editor.focus(); editor.textContent = ''; }"
                    )
                },
            )
            await self._browser_manager.call_tool(
                "browser_type_text", {"text": full_caption}
            )

            # Step 5: Set visibility if not public
            if visibility != "public":
                # Click the visibility dropdown
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": "Everyone"}
                )
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 1000}
                )
                visibility_map = {"friends": "Friends", "private": "Only you"}
                label = visibility_map.get(visibility, "Everyone")
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": label}
                )

            # Step 6: Click Post
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 2000}
            )
            await self._browser_manager.call_tool(
                "browser_click_text", {"text": "Post"}
            )

            # Step 7: Wait for post confirmation
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 6000}
            )

            # Try to get the current URL — may redirect to the video page
            url_result = await self._browser_manager.call_tool(
                "browser_eval",
                {"expression": "window.location.href"},
            )
            current_url = ""
            if isinstance(url_result, dict):
                current_url = url_result.get("result", "")
            elif isinstance(url_result, str):
                current_url = url_result

            video_url = current_url if "/video/" in current_url else ""

            publish_id = await self._log_publish(
                caption=caption,
                file_path=file_path,
                platform_url=video_url,
                status="published" if video_url else "pending",
            )

            return ToolResult(
                success=True,
                data={
                    "publish_id": publish_id,
                    "platform": "tiktok",
                    "caption": caption[:100],
                    "video_url": video_url or "(posted — check TikTok for URL)",
                    "visibility": visibility,
                    "tags": tags,
                },
            )

        except Exception as e:
            logger.error(f"TikTok upload failed: {e}")
            await self._log_publish(
                caption=caption,
                file_path=file_path,
                platform_url="",
                status="failed",
            )
            return ToolResult(success=False, error=f"TikTok upload failed: {e}")
