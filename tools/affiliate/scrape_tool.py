"""affiliate_scrape — Scrape product info from e-commerce pages."""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.browser.eval_utils import eval_value

logger = logging.getLogger(__name__)


class AffiliateScrapeTool(BaseTool):
    """Scrape product information from e-commerce platforms (Amazon, etc.)."""

    def __init__(self) -> None:
        self._browser_manager: Any = None

    @property
    def group(self) -> str:
        return "monetization"

    @property
    def name(self) -> str:
        return "affiliate_scrape"

    @property
    def description(self) -> str:
        return (
            "Scrape product information from an e-commerce page (Amazon, etc.). "
            "Returns structured data: title, price, rating, features, images. "
            "Use before affiliate_pitch to generate marketing content."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Product page URL (Amazon, eBay, etc.).",
                },
                "extract_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to extract. Options: title, price, rating, "
                        "features, images, description. Default: all."
                    ),
                },
            },
            "required": ["url"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._browser_manager:
            return ToolResult(success=False, error="Browser not available.")

        url = params["url"]
        extract_fields = params.get("extract_fields", [])

        try:
            # Navigate to the product page
            await self._browser_manager.call_tool("browser_navigate", {"url": url})
            await self._browser_manager.call_tool(
                "browser_wait", {"milliseconds": 3000}
            )

            # Detect platform and extract accordingly
            is_amazon = "amazon." in url.lower()

            if is_amazon:
                extraction_js = """
                (function() {
                    const data = {};

                    // Title
                    const titleEl = document.getElementById('productTitle');
                    data.title = titleEl ? titleEl.textContent.trim() : '';

                    // Price
                    const priceEl = document.querySelector(
                        '.a-price .a-offscreen'
                    ) || document.querySelector('#priceblock_ourprice')
                      || document.querySelector('#priceblock_dealprice')
                      || document.querySelector('.a-price-whole');
                    data.price = priceEl ? priceEl.textContent.trim() : '';

                    // Rating
                    const ratingEl = document.querySelector(
                        '#acrPopover .a-icon-alt'
                    ) || document.querySelector('.a-icon-star-small .a-icon-alt');
                    data.rating = ratingEl ? ratingEl.textContent.trim() : '';

                    // Review count
                    const reviewEl = document.getElementById(
                        'acrCustomerReviewText'
                    );
                    data.review_count = reviewEl
                        ? reviewEl.textContent.trim() : '';

                    // Features (bullet points)
                    const featureBullets = document.querySelectorAll(
                        '#feature-bullets .a-list-item'
                    );
                    data.features = Array.from(featureBullets)
                        .map(el => el.textContent.trim())
                        .filter(t => t.length > 5)
                        .slice(0, 10);

                    // Main image
                    const imgEl = document.getElementById('landingImage')
                        || document.querySelector('#imgTagWrapperId img');
                    data.image_url = imgEl ? imgEl.src : '';

                    // ASIN from URL
                    const asinMatch = window.location.pathname.match(
                        /\\/dp\\/([A-Z0-9]{10})/
                    );
                    data.product_id = asinMatch ? asinMatch[1] : '';

                    // Description
                    const descEl = document.getElementById(
                        'productDescription'
                    );
                    data.description = descEl
                        ? descEl.textContent.trim().substring(0, 500) : '';

                    return JSON.stringify(data);
                })()
                """
            else:
                # Generic e-commerce extraction
                extraction_js = """
                (function() {
                    const data = {};
                    const meta = (name) => {
                        const el = document.querySelector(
                            `meta[property="${name}"], meta[name="${name}"]`
                        );
                        return el ? el.content : '';
                    };

                    data.title = meta('og:title')
                        || document.title || '';
                    data.price = meta('product:price:amount')
                        || meta('og:price:amount') || '';
                    data.currency = meta('product:price:currency')
                        || meta('og:price:currency') || '';
                    data.description = meta('og:description')
                        || meta('description') || '';
                    data.image_url = meta('og:image') || '';
                    data.url = window.location.href;

                    // Try to find price in page
                    if (!data.price) {
                        const priceEl = document.querySelector(
                            '[class*="price"], [data-testid*="price"]'
                        );
                        data.price = priceEl
                            ? priceEl.textContent.trim() : '';
                    }

                    // Try to find rating
                    const ratingEl = document.querySelector(
                        '[class*="rating"], [class*="stars"]'
                    );
                    data.rating = ratingEl
                        ? ratingEl.textContent.trim().substring(0, 20) : '';

                    data.features = [];
                    data.product_id = '';

                    return JSON.stringify(data);
                })()
                """

            result = await self._browser_manager.call_tool(
                "browser_eval", {"expression": extraction_js}
            )

            # Bridge returns JS values JSON-encoded under "resultJson", not
            # "result". The extraction script itself returns a JSON string
            # (so the bridge double-encodes), which is why we json.loads()
            # twice: once via eval_value to undo the bridge's encoding, then
            # again here to parse the script's own JSON string.
            decoded = eval_value(result)
            raw = decoded if isinstance(decoded, str) else ""

            if not raw:
                return ToolResult(
                    success=False,
                    error="Could not extract product data from page.",
                )

            product_data = json.loads(raw)

            # Filter to requested fields if specified
            if extract_fields:
                product_data = {
                    k: v for k, v in product_data.items() if k in extract_fields
                }

            product_data["source_url"] = url
            product_data["platform"] = "amazon" if is_amazon else "other"

            return ToolResult(success=True, data={"product": product_data})

        except json.JSONDecodeError:
            return ToolResult(
                success=False, error="Failed to parse extracted product data."
            )
        except Exception as e:
            logger.error(f"Affiliate scrape failed: {e}")
            return ToolResult(success=False, error=f"Scrape failed: {e}")
