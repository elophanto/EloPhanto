"""Web search tool — structured search via Search.sh API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://search.sh/api"
_TIMEOUT = 65.0  # API timeout is 60s


class WebSearchTool(BaseTool):
    """Search the web via Search.sh — returns AI answer, sources, and citations."""

    _vault: Any = None  # Injected by agent

    @property
    def group(self) -> str:
        return "data"

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web and get an AI-synthesized answer with ranked sources, "
            "citations, and confidence score. Two modes: 'fast' (3-8s, quick lookup) "
            "and 'deep' (15-30s, generates sub-queries, extracts page content, "
            "cross-references sources). Use this instead of browser_navigate for "
            "research, fact-checking, market research, competitor analysis, and "
            "any task that starts with finding information online."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Max 500 characters.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["fast", "deep"],
                    "description": (
                        "fast: single search + AI answer (3-8s). "
                        "deep: sub-queries, parallel search, page extraction (15-30s). "
                        "Default: fast."
                    ),
                },
                "region": {
                    "type": "string",
                    "description": "ISO country code for regional results (us, gb, de, etc.). Default: us.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max search results (1-20). Default: 10.",
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    def _get_api_key(self) -> str | None:
        if self._vault:
            return self._vault.get("search_sh_api_key")
        return None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                success=False,
                error=(
                    "Search.sh API key not configured. "
                    "Set it with: vault_set key=search_sh_api_key value=sk-sh_..."
                ),
            )

        query = params["query"]
        if len(query) > 500:
            query = query[:500]

        mode = params.get("mode", "fast")
        region = params.get("region", "us")
        max_results = params.get("max_results", 10)

        body: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "region": region,
            "max_results": max_results,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/search",
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )

            if resp.status_code != 200:
                error_text = resp.text
                try:
                    error_data = resp.json()
                    error_text = error_data.get("error", error_text)
                except Exception:
                    pass
                return ToolResult(
                    success=False,
                    error=f"Search.sh API error ({resp.status_code}): {error_text}",
                )

            data = resp.json()

            # Build a clean result
            result: dict[str, Any] = {
                "answer": data.get("answer", ""),
                "confidence": data.get("confidence", 0.0),
                "sources": [
                    {
                        "title": s.get("title", ""),
                        "url": s.get("url", ""),
                        "snippet": s.get("snippet", ""),
                    }
                    for s in data.get("sources", [])
                ],
                "citations": data.get("citations", []),
                "related_queries": data.get("related_queries", []),
                "mode": mode,
            }

            # Deep mode extras
            if mode == "deep":
                result["sub_queries"] = data.get("sub_queries", [])

            duration = data.get("metadata", {}).get("duration_ms", 0)
            if duration:
                result["duration_ms"] = duration

            return ToolResult(success=True, data=result)

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=f"Search.sh request timed out after {_TIMEOUT}s",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Web search failed: {e}")


class WebExtractTool(BaseTool):
    """Extract clean text content from URLs via Search.sh."""

    _vault: Any = None  # Injected by agent

    @property
    def group(self) -> str:
        return "data"

    @property
    def name(self) -> str:
        return "web_extract"

    @property
    def description(self) -> str:
        return (
            "Extract clean text content from one or more URLs. Returns title and "
            "cleaned text (scripts/nav/footer removed, max 5000 chars per page). "
            "Use after web_search to read full page content from specific sources, "
            "or to extract content from any URL."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to extract content from. Max 10 per request.",
                },
            },
            "required": ["urls"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    def _get_api_key(self) -> str | None:
        if self._vault:
            return self._vault.get("search_sh_api_key")
        return None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                success=False,
                error=(
                    "Search.sh API key not configured. "
                    "Set it with: vault_set key=search_sh_api_key value=sk-sh_..."
                ),
            )

        urls = params["urls"]
        if len(urls) > 10:
            urls = urls[:10]

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/extract",
                    json={"urls": urls},
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )

            if resp.status_code != 200:
                error_text = resp.text
                try:
                    error_data = resp.json()
                    error_text = error_data.get("error", error_text)
                except Exception:
                    pass
                return ToolResult(
                    success=False,
                    error=f"Search.sh extract error ({resp.status_code}): {error_text}",
                )

            data = resp.json()
            pages = data.get("pages", [])

            return ToolResult(
                success=True,
                data={
                    "pages": [
                        {
                            "url": p.get("url", ""),
                            "title": p.get("title", ""),
                            "content": p.get("content", ""),
                        }
                        for p in pages
                    ],
                    "count": len(pages),
                },
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=f"Search.sh extract timed out after {_TIMEOUT}s",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Web extract failed: {e}")
