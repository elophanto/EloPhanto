"""Browser utility functions — content sanitization."""

from __future__ import annotations

import re


def sanitize_content(html: str) -> str:
    """Sanitize HTML content by removing scripts, styles, handlers, and secrets."""
    if not html:
        return html

    # Remove <script> tags and content
    html = re.sub(
        r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )

    # Remove <style> tags and content
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove on* event handlers
    html = re.sub(
        r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*')""",
        "",
        html,
        flags=re.IGNORECASE,
    )

    # Redact password input values
    html = re.sub(
        r'(<input[^>]*type\s*=\s*"password"[^>]*value\s*=\s*")[^"]*(")',
        r"\1[REDACTED]\2",
        html,
        flags=re.IGNORECASE,
    )

    # Replace large base64 data URIs (> 100KB)
    def _replace_large_data_uri(match: re.Match[str]) -> str:
        if len(match.group(0)) > 100_000:
            return "[LARGE_DATA_URI]"
        return match.group(0)

    html = re.sub(r"data:[^;]+;base64,[A-Za-z0-9+/=]+", _replace_large_data_uri, html)

    return html
