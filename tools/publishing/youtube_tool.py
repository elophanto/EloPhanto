"""youtube_upload — Upload videos to YouTube via browser bridge."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_YOUTUBE_STUDIO_UPLOAD = "https://studio.youtube.com/channel/UC/videos/upload?d=ud"
_MAX_TITLE = 100
_MAX_DESCRIPTION = 5000


class YouTubeUploadTool(BaseTool):
    """Upload a video file to YouTube (regular or Shorts)."""

    def __init__(self) -> None:
        self._browser_manager: Any = None
        self._db: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "youtube_upload"

    @property
    def description(self) -> str:
        return (
            "Upload a video file to YouTube. Supports regular videos and "
            "Shorts. Uses pre-authenticated Chrome profile — user must be "
            "logged into YouTube in Chrome. Returns the published video URL."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Local path to the video file (MP4 or WebM).",
                },
                "title": {
                    "type": "string",
                    "description": f"Video title (max {_MAX_TITLE} chars).",
                },
                "description": {
                    "type": "string",
                    "description": "Video description text.",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["public", "unlisted", "private"],
                    "description": "Visibility setting (default: unlisted).",
                },
                "is_short": {
                    "type": "boolean",
                    "description": "If true, tag as YouTube Short (video must be ≤60s, 9:16).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Video tags for discoverability.",
                },
            },
            "required": ["file_path", "title"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def _log_publish(
        self,
        title: str,
        file_path: str,
        platform_url: str,
        status: str,
        campaign_id: str = "",
    ) -> str:
        """Log to publishing_log table. Returns publish_id."""
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
                    "youtube",
                    "video",
                    title,
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
        title = params["title"]
        description = params.get("description", "")
        visibility = params.get("visibility", "unlisted")
        is_short = params.get("is_short", False)
        tags = params.get("tags", [])

        # Validate file exists
        if not os.path.isfile(file_path):
            return ToolResult(success=False, error=f"Video file not found: {file_path}")

        if len(title) > _MAX_TITLE:
            return ToolResult(
                success=False,
                error=f"Title exceeds {_MAX_TITLE} chars ({len(title)}).",
            )

        if is_short:
            title = f"{title} #Shorts" if "#Shorts" not in title else title

        try:
            # Step 1: Navigate to YouTube Studio upload page
            await self._browser_manager.call_tool(
                "browser_navigate", {"url": _YOUTUBE_STUDIO_UPLOAD}
            )

            # Step 2: Wait for upload button/area and set file
            # YouTube Studio uses a file input — find it and set the file
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 3000}
            )

            # Look for the file input element and upload
            page = await self._browser_manager.agent.getPage()
            file_input = await page.querySelector('input[type="file"]')
            if file_input:
                await file_input.setInputFiles(file_path)
            else:
                # Try clicking the upload button to trigger file chooser
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": "SELECT FILES"}
                )
                await self._browser_manager.agent.uploadFileChooser([file_path])

            # Step 3: Wait for upload to start processing
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 5000}
            )

            # Step 4: Fill in title
            # YouTube Studio pre-fills filename — clear and type new title
            await self._browser_manager.call_tool(
                "browser_eval",
                {
                    "expression": (
                        "const titleBox = document.querySelector("
                        "'div#textbox[aria-label=\"Add a title that describes your video\"]'"
                        ") || document.querySelector('#title-textarea #textbox');"
                        "if (titleBox) { titleBox.textContent = ''; titleBox.focus(); }"
                    )
                },
            )
            await self._browser_manager.call_tool("browser_type_text", {"text": title})

            # Step 5: Fill description if provided
            if description:
                desc_text = description[:_MAX_DESCRIPTION]
                await self._browser_manager.call_tool(
                    "browser_eval",
                    {
                        "expression": (
                            "const descBox = document.querySelector("
                            "'div#textbox[aria-label=\"Tell viewers about your video\"]'"
                            ") || document.querySelector('#description-textarea #textbox');"
                            "if (descBox) { descBox.focus(); }"
                        )
                    },
                )
                await self._browser_manager.call_tool(
                    "browser_type_text", {"text": desc_text}
                )

            # Step 6: Set "Not made for kids"
            await self._browser_manager.call_tool(
                "browser_click_text", {"text": "No, it's not made for kids"}
            )

            # Step 7: Navigate through the wizard — click Next 3 times
            for _ in range(3):
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 1500}
                )
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": "Next"}
                )

            # Step 8: Set visibility
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 2000}
            )
            visibility_labels = {
                "public": "Public",
                "unlisted": "Unlisted",
                "private": "Private",
            }
            await self._browser_manager.call_tool(
                "browser_click_text",
                {"text": visibility_labels.get(visibility, "Unlisted")},
            )

            # Step 9: Click Publish/Save
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 2000}
            )
            button_text = "Publish" if visibility != "private" else "Save"
            await self._browser_manager.call_tool(
                "browser_click_text", {"text": button_text}
            )

            # Step 10: Wait for publish confirmation and extract URL
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 5000}
            )

            # Try to extract the video URL from the confirmation dialog
            url_result = await self._browser_manager.call_tool(
                "browser_eval",
                {
                    "expression": (
                        "const link = document.querySelector("
                        "'a.style-scope.ytcp-video-info[href*=\"youtu\"]'"
                        ") || document.querySelector('a[href*=\"/video/\"]');"
                        "link ? link.href : ''"
                    )
                },
            )
            video_url = ""
            if isinstance(url_result, dict):
                video_url = url_result.get("result", "")
            elif isinstance(url_result, str):
                video_url = url_result

            publish_id = await self._log_publish(
                title=title,
                file_path=file_path,
                platform_url=video_url,
                status="published" if video_url else "pending",
            )

            return ToolResult(
                success=True,
                data={
                    "publish_id": publish_id,
                    "platform": "youtube",
                    "title": title,
                    "video_url": video_url or "(check YouTube Studio for URL)",
                    "visibility": visibility,
                    "is_short": is_short,
                    "tags": tags,
                },
            )

        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            await self._log_publish(
                title=title,
                file_path=file_path,
                platform_url="",
                status="failed",
            )
            return ToolResult(success=False, error=f"YouTube upload failed: {e}")
