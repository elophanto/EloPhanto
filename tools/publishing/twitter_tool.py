"""twitter_post — Post text and media to X (Twitter) via browser bridge."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.browser.eval_utils import eval_value

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

            # Step 2: Find and click the text area — try multiple selectors.
            # Wrap as an IIFE so the script always returns a value the bridge
            # can JSON-stringify; previously a multi-statement eval combined
            # with reading the wrong result key (resultJson vs result) made
            # this loop silently fail on every call.
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
                                "(() => { const el = document.querySelector("
                                + json.dumps(selector)
                                + "); if (el) { el.focus(); return 'found'; }"
                                " return ''; })()"
                            )
                        },
                    )
                    val = eval_value(result)
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

            # Step 4: Attach media if provided.
            # Previous code did `await self._browser_manager.agent.getPage()`
            # — that attribute doesn't exist on BrowserManager, so this branch
            # always threw. Replaced with a sequence that uses only public
            # bridge tools: refresh the element tree, look up the file input's
            # element index, then call browser_upload_file with the absolute
            # local path. setInputFiles-equivalent without touching the
            # bridge or relying on indexes the agent doesn't have a hook into.
            if media_path:
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 1000}
                )
                # Make sure the bridge has indexed the file input — it's
                # hidden, but it IS an <input> so the bridge's interactive
                # selector picks it up.
                await self._browser_manager.call_tool(
                    "browser_get_elements", {"showAll": True, "compact": True}
                )
                # Read the data-aware-idx the bridge stamped on the input.
                idx_result = await self._browser_manager.call_tool(
                    "browser_eval",
                    {
                        "expression": (
                            "(() => {"
                            " const el = document.querySelector("
                            "'input[data-testid=\"fileInput\"]')"
                            " || document.querySelector('input[type=\"file\"]');"
                            " if (!el) return -1;"
                            " const idx = el.getAttribute('data-aware-idx');"
                            " return idx === null ? -1 : Number(idx);"
                            " })()"
                        )
                    },
                )
                file_input_idx = eval_value(idx_result)
                if isinstance(file_input_idx, int) and file_input_idx >= 0:
                    try:
                        await self._browser_manager.call_tool(
                            "browser_upload_file",
                            {"index": file_input_idx, "files": [media_path]},
                        )
                    except Exception as upload_err:
                        logger.warning(
                            "browser_upload_file failed for index %d: %s",
                            file_input_idx,
                            upload_err,
                        )
                else:
                    logger.warning(
                        "Could not locate file input on X compose page; "
                        "tweet will be posted without media."
                    )

                # Wait for media to upload + thumbnail to render
                await self._browser_manager.call_tool(
                    "browser_wait", {"milliseconds": 4000}
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
            current_url_value = eval_value(url_result)
            current_url = (
                current_url_value if isinstance(current_url_value, str) else ""
            )

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
