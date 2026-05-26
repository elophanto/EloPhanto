"""voice_extract — read operator-curated exemplars, propose a voice.yaml.

Operator drops 5-20 markdown files at
``data/companies/<slug>/exemplars/<channel>/*.md`` (each file is one
post / email with an optional ``author``/``date``/``channel``/``notes``
front-matter then ``---`` then the body). This tool reads them, asks
the LLM to distill recurring hooks / tone / banned-phrase candidates,
and writes a *proposed* voice.yaml to
``data/companies/<slug>/voice_proposed.yaml``. Operator reviews and
promotes by renaming to ``voice.yaml`` (or by editing the proposal).

Deliberately writes to a *_proposed.yaml file rather than overwriting
voice.yaml — the operator's approved voice is sacred state; the LLM's
extraction is a suggestion.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are extracting a writing-voice contract from operator-curated "
    "exemplars. Output ONLY a JSON object with these keys:\n"
    "  persona (string), tone (list[string]), "
    "length_target ({min_chars: int, max_chars: int}), "
    "allowed_hooks (list[string], 3-6 hook TEMPLATES with <slot> "
    "placeholders for variable parts), "
    "banned_phrases (list[string], generic / corporate / AI-slop "
    "phrases that do NOT appear in the exemplars but commonly creep "
    "into LLM drafts — e.g. 'leverage', 'unlock', 'in today's fast-"
    "paced world', 'are you tired of'), "
    "banned_patterns (list[{regex, reason}], 1-3 regex patterns for "
    "openings to avoid — e.g. self-focused 'We help X' openers), "
    "cta_style (string, one short sentence on how CTAs work in this "
    "voice).\n"
    "Be specific and concrete. The exemplars are the truth — extract "
    "what's there. Do NOT include preamble, code fences, or commentary."
)


class VoiceExtractTool(BaseTool):
    def __init__(self) -> None:
        self._voice_manager: Any = None
        self._router: Any = None
        self._company_manager: Any = None

    @property
    def name(self) -> str:
        return "voice_extract"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def description(self) -> str:
        return (
            "Read operator-curated exemplars at data/companies/<slug>/"
            "exemplars/<channel>/*.md and propose voice_proposed.yaml. "
            "Requires ≥2 files per channel. Operator promotes via "
            "`elophanto voice approve`. See voice-extraction-workflow skill."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": (
                        "Which exemplars subdir to read (e.g. "
                        "'twitter', 'email', 'linkedin'). Defaults to "
                        "scanning all channel subdirs and merging."
                    ),
                },
                "company_id": {
                    "type": "string",
                    "description": "Defaults to the active company.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._voice_manager is None:
            return ToolResult(
                success=False,
                error="voice_extract not initialized (missing voice_manager)",
            )
        if self._router is None:
            return ToolResult(
                success=False,
                error="voice_extract not initialized (missing router)",
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        channel_filter = str(params.get("channel") or "").strip()

        voice_path = self._voice_manager.voice_path(company_id)
        if voice_path is None:
            return ToolResult(
                success=False,
                error="voice_extract: no project_root configured",
            )
        # voice.yaml lives at data/companies/<co>/voice.yaml; the
        # exemplars dir is the sibling exemplars/ folder.
        exemplars_root = voice_path.parent / "exemplars"

        if not exemplars_root.is_dir():
            return ToolResult(
                success=False,
                error=(
                    f"No exemplars dir at {exemplars_root}. "
                    "Operator should drop 5-20 example posts/emails "
                    "into <that dir>/<channel>/*.md before running "
                    "voice_extract."
                ),
            )

        exemplars = _collect_exemplars(exemplars_root, channel_filter)
        if len(exemplars) < 2:
            return ToolResult(
                success=False,
                error=(
                    f"Found only {len(exemplars)} exemplar(s) under "
                    f"{exemplars_root}"
                    + (f"/{channel_filter}" if channel_filter else "")
                    + ". Need at least 2 to extract a voice."
                ),
            )

        prompt = _build_prompt(exemplars)
        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                task_type="planning",
                temperature=0.3,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"LLM extraction failed: {e}")

        content = (response.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            proposal = json.loads(content)
        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                error=(
                    f"LLM returned non-JSON ({e}). First 200 chars: "
                    f"{content[:200]!r}"
                ),
            )
        if not isinstance(proposal, dict):
            return ToolResult(
                success=False,
                error="LLM output JSON was not a mapping",
            )

        proposal_path = voice_path.parent / "voice_proposed.yaml"
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml

            proposal_path.write_text(
                yaml.safe_dump(proposal, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as e:
            return ToolResult(
                success=False, error=f"failed to write proposal yaml: {e}"
            )

        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "exemplar_count": len(exemplars),
                "channels": sorted({ex["channel"] for ex in exemplars}),
                "proposal_path": str(proposal_path),
                "voice_path": str(self._voice_manager.voice_path(company_id)),
                "next": (
                    "Operator reviews voice_proposed.yaml and (if "
                    "good) renames it to voice.yaml. Then call "
                    "voice_show to confirm, and future drafts will be "
                    "lint-gated against it."
                ),
            },
        )


def _collect_exemplars(root: Path, channel_filter: str) -> list[dict[str, str]]:
    """Walk ``root/<channel>/*.md`` and return one dict per file."""
    out: list[dict[str, str]] = []
    channel_dirs: list[Path]
    if channel_filter:
        target = root / channel_filter
        channel_dirs = [target] if target.is_dir() else []
    else:
        channel_dirs = [d for d in root.iterdir() if d.is_dir()]
    for ch_dir in sorted(channel_dirs):
        for md in sorted(ch_dir.glob("*.md")):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("voice_extract: skip %s: %s", md, e)
                continue
            out.append(
                {
                    "channel": ch_dir.name,
                    "filename": md.name,
                    "text": text.strip(),
                }
            )
    return out


def _build_prompt(exemplars: list[dict[str, str]]) -> str:
    """Render exemplars into a single user prompt. Cap each at 1500
    chars to keep token budget bounded for operators who paste in
    long-form pieces."""
    parts = [
        f"EXEMPLAR COUNT: {len(exemplars)}",
        f"CHANNELS: {sorted({ex['channel'] for ex in exemplars})}",
        "",
        "Each exemplar below is one post / email the operator picked "
        "as representative of the target voice. Extract the recurring "
        "patterns. Output JSON only.",
        "",
    ]
    for i, ex in enumerate(exemplars, 1):
        body = ex["text"][:1500]
        parts.append(
            f"--- exemplar {i} [channel={ex['channel']}, "
            f"file={ex['filename']}] ---\n{body}\n"
        )
    return "\n".join(parts)
