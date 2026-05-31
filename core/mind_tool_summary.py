"""Human-readable summaries of tool calls + their artifacts.

The mind dashboard used to render ``MND tool: file_write`` with zero
context, leaving the operator unable to tell if the agent was reading
config, scribbling in workspace, or shipping a real artifact. This
module translates a tool call into:

  - a verb-first one-liner ("Wrote audience-brief.md")
  - an optional artifact preview (first 240 chars of the content, plus
    the file path / heading / first H1) so the operator can see the
    OUTCOME, not just the process

Used by ``core/autonomous_mind.py:_on_tool`` to enrich the
``MIND_TOOL_USE`` event payload. Dashboard renderers consume the new
fields without any schema change — old payloads with ``params=""``
still work, the new fields are additive.

Why a separate module: the logic is data-mapping with no async / no
state, and we want it unit-testable without spinning up the agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Verb forms for the most common tool families. Anything not listed
# falls through to the raw tool name — better to show the truth than
# invent a guess.
_VERBS: dict[str, str] = {
    "file_write": "Wrote",
    "file_read": "Read",
    "file_edit": "Edited",
    "file_delete": "Deleted",
    "knowledge_write": "Saved lesson",
    "knowledge_search": "Searched memory for",
    "knowledge_read": "Read lesson",
    "skill_read": "Loaded skill",
    "skill_list": "Listed skills",
    "skill_search": "Searched skills",
    "skill_promote": "Promoted skill",
    "skill_create": "Created skill",
    "shell_execute": "Ran shell",
    "web_search": "Searched the web for",
    "web_extract": "Read web page",
    "browser_navigate": "Navigated to",
    "browser_click_text": "Clicked",
    "browser_extract": "Extracted from page",
    "browser_eval": "Ran JS",
    "twitter_post": "Posted to X",
    "twitter_reply": "Replied on X",
    "x_style_preflight": "Checked X style on",
    "email_send": "Sent email",
    "email_draft": "Drafted email",
    "update_scratchpad": "Updated scratchpad",
    "set_next_wakeup": "Set next wakeup",
    "role_use": "Switched to role",
    "role_show": "Inspected role",
    "role_list": "Listed roles",
    "company_use": "Switched to company",
    "company_report": "Read company report",
    "company_list": "Listed companies",
    "company_create": "Created company",
    "company_set_product": "Set company product",
    "company_plan_apply": "Applied company plan",
    "goal_create": "Created goal",
    "goal_advance": "Advanced goal",
    "goal_complete": "Completed goal",
    "goal_list": "Listed goals",
    "self_create_plugin": "Built new tool",
    "affect_record_event": "Felt",
    "schedule_create": "Scheduled",
    "schedule_run": "Ran schedule",
}

# Param keys to inspect for an object/target string, in priority order.
# We pick the first non-empty one found per tool call.
_OBJECT_KEYS: tuple[str, ...] = (
    "path",
    "name",
    "skill_name",
    "url",
    "query",
    "text",
    "content",
    "slug",
    "goal_id",
    "schedule_id",
    "tool_name",
    "command",
    "to",
    "subject",
    "title",
)


def _shorten_path(value: str, max_chars: int = 48) -> str:
    """Compact a long absolute path to ``…/parent/leaf``.

    Reduces visual noise from workspace paths that take 80+ chars
    while preserving the meaningful tail (which directory + which
    file). Absolute Unix paths get the ``…`` prefix; short paths
    pass through untouched.
    """
    if len(value) <= max_chars:
        return value
    try:
        p = Path(value)
        parts = p.parts
        if len(parts) <= 2:
            return value
        tail = "/".join(parts[-2:])
        return f"…/{tail}"
    except Exception:
        return value[-max_chars:]


def _extract_object(params: dict[str, Any]) -> str:
    """Pick the most useful object/target string from a params dict.

    Strings are preferred over containers; the first key in
    ``_OBJECT_KEYS`` with a non-empty string value wins. Returns
    ``""`` when nothing useful is present (e.g. ``role_list`` with no
    args) — the renderer falls back to the verb alone.
    """
    for key in _OBJECT_KEYS:
        if key in params:
            raw = params[key]
            if isinstance(raw, str) and raw.strip():
                value = raw.strip()
                # Compact obvious paths so they don't dominate the line
                if value.startswith("/") or value.startswith("~/"):
                    return _shorten_path(value)
                return value
    return ""


def summarize_call(tool_name: str, params: dict[str, Any]) -> str:
    """One-line `Verb object` describing what the tool was called on.

    Examples (with params):
      file_write       {path: '~/agents/.../brief.md', content: '...'}
        → "Wrote …/research/brief.md"
      knowledge_search {query: 'recent X reply lessons'}
        → "Searched memory for: recent X reply lessons"
      role_use         {name: 'sales'}
        → "Switched to role: sales"
      file_read        {} (e.g. listing)
        → "file_read" (verb fallback to raw name when no object)
    """
    verb = _VERBS.get(tool_name)
    obj = _extract_object(params or {})

    if verb is None:
        # Unknown tool — show the raw name + object so operators can
        # still tell what's happening. Don't invent a verb.
        return f"{tool_name}: {obj}" if obj else tool_name

    if not obj:
        return verb

    # Most verbs read better with a colon ("Searched memory for: X");
    # path verbs read better without ("Wrote brief.md"). Heuristic:
    # if the verb ends with "for" or "on" or contains a colon already,
    # add the colon; otherwise glue the object directly.
    if verb.endswith((" for", " on", " to", " of")):
        return f"{verb}: {obj}"
    if " " in verb:
        return f"{verb} {obj}"
    return f"{verb} {obj}"


# ── Artifact preview — the "so what" of the call ─────────────────────────


# Param keys that carry user-visible content the operator might want to
# read inline. Order = priority (the first non-empty wins).
_CONTENT_KEYS: tuple[str, ...] = (
    "content",
    "body",
    "text",
    "message",
)

# Max chars surfaced inline. Long enough to capture a meaningful first
# paragraph + headline; short enough to keep the dashboard scannable.
PREVIEW_MAX_CHARS = 240


def _first_meaningful_line(text: str) -> str:
    """Return the first non-empty, non-noisy line.

    Skips markdown frontmatter (``---``), the contents of fenced code
    blocks (```` ``` ```` … ```` ``` ````), and leading whitespace.
    Markdown headings (``# Title``) are surfaced verbatim — the
    heading IS the point. If the entire document is wrapped in a
    code fence we still return the first code line so we never reply
    with an empty preview.
    """
    if not text:
        return ""
    in_frontmatter = False
    in_code_fence = False
    fallback = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Code-fence toggle: every ``` line flips the state and is
        # itself skipped. Lines BETWEEN fences are treated as code
        # and skipped too — we want the surrounding prose / headline.
        if line.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            # Remember the first code line as a fallback in case the
            # whole content is wrapped in a single fence with no prose
            # outside it.
            if not fallback:
                fallback = line
            continue
        # Frontmatter toggle: --- delimits a YAML/TOML block. Same
        # pattern as code fences.
        if line == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        return line
    return fallback


def extract_artifact_preview(
    tool_name: str, params: dict[str, Any], *, max_chars: int = PREVIEW_MAX_CHARS
) -> str:
    """Return a short preview of any artifact the tool call produced.

    For write-style tools (file_write, knowledge_write, twitter_post,
    update_scratchpad), surfaces the first meaningful line of the
    content plus a truncated body, so the operator can see WHAT was
    written, not just THAT something was written.

    Returns ``""`` for tools without surfaceable content (file_read,
    knowledge_search, role_use, etc.) — the caller should hide the
    preview slot rather than render an empty quote.
    """
    if not params:
        return ""
    for key in _CONTENT_KEYS:
        if key in params:
            raw = params[key]
            if not isinstance(raw, str) or not raw.strip():
                continue
            content = raw.strip()
            headline = _first_meaningful_line(content)
            # If the headline IS the content (short post / tweet),
            # just return it whole.
            if len(content) <= max_chars:
                return content
            # Otherwise: headline on its own line + truncated body.
            # The headline alone is often the most useful slice.
            if headline and len(headline) < len(content) - 20:
                body_tail = content[len(headline) :].lstrip("\n").strip()
                trimmed = body_tail[: max_chars - len(headline) - 4]
                return f"{headline}\n{trimmed}…"
            return content[:max_chars] + "…"
    return ""
