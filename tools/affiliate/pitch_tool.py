"""affiliate_pitch — Generate marketing pitch from product data."""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_PLATFORM_LIMITS = {
    "twitter": 260,  # Leave room for link
    "tiktok": 150,  # Short caption
    "youtube": 500,  # Description excerpt
}

_PITCH_SYSTEM = (
    "You are a concise copywriter. Generate a short, engaging marketing pitch "
    "for the product below. The pitch should feel natural and authentic — not "
    "salesy or spammy. Include a clear call-to-action."
)


class AffiliatePitchTool(BaseTool):
    """Generate a marketing pitch for a product using LLM."""

    def __init__(self) -> None:
        self._router: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "affiliate_pitch"

    @property
    def description(self) -> str:
        return (
            "Generate a marketing pitch for a product. Takes product data "
            "(from affiliate_scrape) and a target platform. Returns pitch "
            "text, suggested hashtags, and call-to-action. Uses LLM."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product_data": {
                    "type": "object",
                    "description": "Product data from affiliate_scrape (title, price, features, etc.).",
                },
                "platform": {
                    "type": "string",
                    "enum": ["twitter", "tiktok", "youtube"],
                    "description": "Target platform for the pitch.",
                },
                "tone": {
                    "type": "string",
                    "enum": ["casual", "professional", "enthusiastic"],
                    "description": "Pitch tone (default: casual).",
                },
                "affiliate_link": {
                    "type": "string",
                    "description": "Affiliate URL to include in the pitch.",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Max character count (default: platform limit).",
                },
            },
            "required": ["product_data", "platform"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="LLM router not available.")

        product_data = params["product_data"]
        platform = params["platform"]
        tone = params.get("tone", "casual")
        affiliate_link = params.get("affiliate_link", "")
        max_length = params.get("max_length", _PLATFORM_LIMITS.get(platform, 280))

        title = product_data.get("title", "Unknown Product")
        price = product_data.get("price", "")
        features = product_data.get("features", [])
        rating = product_data.get("rating", "")

        prompt = (
            f"Product: {title}\n"
            f"Price: {price}\n"
            f"Rating: {rating}\n"
            f"Features: {', '.join(features[:5]) if features else 'N/A'}\n\n"
            f"Platform: {platform}\n"
            f"Tone: {tone}\n"
            f"Max length: {max_length} chars\n"
            f"{'Include link: ' + affiliate_link if affiliate_link else ''}\n\n"
            "Return ONLY a JSON object with these fields:\n"
            '- "pitch": the marketing text (respect max length)\n'
            '- "hashtags": array of 3-5 relevant hashtags (no # prefix)\n'
            '- "cta": a short call-to-action phrase\n'
            "Return ONLY the JSON, nothing else."
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _PITCH_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                task_type="simple",
            )

            content = response.content.strip()
            # Clean markdown wrappers
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)
            pitch = result.get("pitch", "")
            hashtags = result.get("hashtags", [])
            cta = result.get("cta", "")

            # Enforce max length
            if len(pitch) > max_length:
                pitch = pitch[: max_length - 3] + "..."

            return ToolResult(
                success=True,
                data={
                    "pitch": pitch,
                    "hashtags": hashtags,
                    "cta": cta,
                    "platform": platform,
                    "product_title": title,
                    "char_count": len(pitch),
                },
            )

        except json.JSONDecodeError:
            # LLM returned non-JSON — use raw content as pitch
            return ToolResult(
                success=True,
                data={
                    "pitch": content[:max_length] if content else "",
                    "hashtags": [],
                    "cta": "",
                    "platform": platform,
                    "product_title": title,
                    "char_count": len(content) if content else 0,
                    "note": "LLM returned plain text instead of JSON.",
                },
            )
        except Exception as e:
            logger.error(f"Affiliate pitch failed: {e}")
            return ToolResult(success=False, error=f"Pitch generation failed: {e}")
