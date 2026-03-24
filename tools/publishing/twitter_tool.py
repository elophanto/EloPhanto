"""twitter_post — Post text and media to X (Twitter) via browser bridge."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_X_COMPOSE_URL = "https://x.com/compose/post"
_MAX_TWEET_CHARS = 280


class TwitterPostTool(BaseTool):
    """Post text and/or media to X (Twitter)."""

    def __init__(self) -> None:
        self._browser_manager: Any = None
        self._db: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "twitter_post"

    @property
    def description(self) -> str:
        return (
            "Post text and/or media to X (Twitter). Uses pre-authenticated "
            "Chrome profile. Can attach an image or video. Returns the "
            "published tweet URL. Max 280 chars."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": f"Tweet text (max {_MAX_TWEET_CHARS} chars).",
                },
                "media_path": {
                    "type": "string",
                    "description": "Local path to image or video to attach (optional).",
                },
                "reply_to_url": {
                    "type": "string",
                    "description": "URL of a tweet to reply to (optional).",
                },
            },
            "required": ["content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def _log_publish(
        self,
        content: str,
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
                "VALUES (?, ?, ?, ?, '', ?, ?, '{}', ?, ?, ?)",
                (
                    publish_id,
                    "twitter",
                    "text",
                    content[:100],
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

        content = params["content"]
        media_path = params.get("media_path", "")
        reply_to_url = params.get("reply_to_url", "")

        if len(content) > _MAX_TWEET_CHARS:
            return ToolResult(
                success=False,
                error=f"Tweet exceeds {_MAX_TWEET_CHARS} chars ({len(content)}).",
            )

        if media_path and not os.path.isfile(media_path):
            return ToolResult(
                success=False, error=f"Media file not found: {media_path}"
            )

        try:
            # Step 1: Navigate to compose page or reply URL
            target_url = reply_to_url if reply_to_url else _X_COMPOSE_URL
            await self._browser_manager.call_tool(
                "browser_navigate", {"url": target_url}
            )
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 3000}
            )

            # If replying, click the reply button first
            if reply_to_url:
                await self._browser_manager.call_tool(
                    "browser_click_text", {"text": "Reply"}
                )
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 2000}
                )

            # Step 2: Find and click the text area — try multiple selectors
            selectors = [
                'div[data-testid="tweetTextarea_0"][role="textbox"]',
                'div[data-testid="tweetTextarea_0"] div[role="textbox"]',
                'div[role="textbox"]',
            ]
            focused = False
            for selector in selectors:
                try:
                    result = await self._browser_manager.call_tool(
                        "browser_eval",
                        {
                            "expression": (
                                f"const el = document.querySelector('{selector}');"
                                "if (el) { el.focus(); 'found'; } else { ''; }"
                            )
                        },
                    )
                    val = (
                        result.get("result", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    if val == "found":
                        focused = True
                        break
                except Exception:
                    continue

            if not focused:
                return ToolResult(
                    success=False,
                    error="Could not find tweet text box. Is X logged in?",
                )

            # Step 3: Type the content
            await self._browser_manager.call_tool(
                "browser_type_text", {"text": content}
            )

            # Step 4: Attach media if provided
            if media_path:
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 1000}
                )
                # Find the media upload input
                page = await self._browser_manager.agent.getPage()
                file_input = await page.querySelector('input[data-testid="fileInput"]')
                if file_input:
                    await file_input.setInputFiles(media_path)
                else:
                    # Fallback: try generic file input
                    file_input = await page.querySelector('input[type="file"]')
                    if file_input:
                        await file_input.setInputFiles(media_path)

                # Wait for media to upload
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 3000}
                )

            # Step 5: Click Post button
            await self._browser_manager.call_tool(
                "browser_click_text", {"text": "Post"}
            )

            # Step 6: Wait and extract tweet URL
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 4000}
            )

            # After posting, X redirects or shows the tweet
            url_result = await self._browser_manager.call_tool(
                "browser_eval",
                {"expression": "window.location.href"},
            )
            current_url = ""
            if isinstance(url_result, dict):
                current_url = url_result.get("result", "")
            elif isinstance(url_result, str):
                current_url = url_result

            # Check if we're on a tweet page (contains /status/)
            tweet_url = current_url if "/status/" in current_url else ""

            publish_id = await self._log_publish(
                content=content,
                platform_url=tweet_url,
                status="published",
            )

            return ToolResult(
                success=True,
                data={
                    "publish_id": publish_id,
                    "platform": "twitter",
                    "content": content,
                    "tweet_url": tweet_url or "(posted — check X for URL)",
                    "has_media": bool(media_path),
                },
            )

        except Exception as e:
            logger.error(f"Twitter post failed: {e}")
            await self._log_publish(content=content, platform_url="", status="failed")
            return ToolResult(success=False, error=f"Twitter post failed: {e}")
