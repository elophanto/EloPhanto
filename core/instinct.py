"""Instinct-based learning: atomic learned behaviors with confidence scoring.

An instinct is smaller than a lesson — one trigger, one action, with
confidence scoring, project scoping, and evolution tracking.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Instinct:
    """Single atomic learned behavior."""

    id: str
    trigger: str  # When this applies
    action: str  # What to do
    confidence: float = 0.3  # 0.3 tentative → 0.9 near certain
    evidence: list[str] = field(default_factory=list)
    scope: str = "project"  # "project" or "global"
    project_hash: str = ""  # Git remote URL hash
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    observation_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Instinct:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def make_instinct_id(trigger: str, action: str) -> str:
    """Deterministic ID from trigger+action."""
    content = f"{trigger.strip().lower()}:{action.strip().lower()}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def get_project_hash(project_root: Path) -> str:
    """Get a portable project hash from git remote URL."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return hashlib.sha256(result.stdout.strip().encode()).hexdigest()[:12]
    except Exception:
        pass
    # Fallback: hash the absolute path
    return hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:12]


class InstinctStore:
    """Manages instinct storage, retrieval, and merging."""

    def __init__(self, data_dir: Path, project_hash: str = "") -> None:
        self._data_dir = data_dir / "instincts"
        self._project_hash = project_hash
        self._project_dir = (
            self._data_dir / "project" / project_hash if project_hash else None
        )
        self._global_dir = self._data_dir / "global"

    def _ensure_dirs(self) -> None:
        self._global_dir.mkdir(parents=True, exist_ok=True)
        if self._project_dir:
            self._project_dir.mkdir(parents=True, exist_ok=True)

    def save(self, instinct: Instinct) -> None:
        """Save an instinct to the appropriate directory."""
        self._ensure_dirs()
        if instinct.scope == "global":
            path = self._global_dir / f"instinct_{instinct.id}.json"
        else:
            if not self._project_dir:
                return
            path = self._project_dir / f"instinct_{instinct.id}.json"

        # Write provenance alongside
        path.write_text(json.dumps(instinct.to_dict(), indent=2), encoding="utf-8")
        provenance_path = path.with_suffix(".provenance.json")
        provenance_path.write_text(
            json.dumps(
                {
                    "source": "instinct-extraction",
                    "created_at": instinct.created_at,
                    "confidence": instinct.confidence,
                    "evidence_count": len(instinct.evidence),
                    "author": "auto-extracted",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def load(self, instinct_id: str) -> Instinct | None:
        """Load an instinct by ID (checks project then global)."""
        for d in [self._project_dir, self._global_dir]:
            if d is None:
                continue
            path = d / f"instinct_{instinct_id}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return Instinct.from_dict(data)
                except Exception:
                    pass
        return None

    def find_by_trigger(self, trigger: str, threshold: float = 0.6) -> Instinct | None:
        """Find an existing instinct with a similar trigger (fuzzy)."""
        trigger_lower = trigger.strip().lower()
        trigger_words = set(trigger_lower.split())

        best_match: Instinct | None = None
        best_overlap = 0.0

        for instinct in self.list_all():
            inst_words = set(instinct.trigger.strip().lower().split())
            if not inst_words or not trigger_words:
                continue
            overlap = len(trigger_words & inst_words) / max(
                len(trigger_words), len(inst_words)
            )
            if overlap > best_overlap and overlap >= threshold:
                best_overlap = overlap
                best_match = instinct

        return best_match

    def list_all(self, scope: str | None = None) -> list[Instinct]:
        """List all instincts, optionally filtered by scope."""
        instincts: list[Instinct] = []
        dirs: list[Path | None] = []

        if scope is None or scope == "project":
            dirs.append(self._project_dir)
        if scope is None or scope == "global":
            dirs.append(self._global_dir)

        for d in dirs:
            if d is None or not d.exists():
                continue
            for path in d.glob("instinct_*.json"):
                if path.suffix == ".json" and ".provenance" not in path.name:
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        instincts.append(Instinct.from_dict(data))
                    except Exception:
                        pass

        return instincts

    def merge_or_create(
        self,
        trigger: str,
        action: str,
        evidence: str,
        tags: list[str],
        scope: str = "project",
    ) -> Instinct:
        """Merge with existing instinct or create new one."""
        now = datetime.now(UTC).isoformat()

        # Check for existing similar instinct
        existing = self.find_by_trigger(trigger)
        if existing:
            # Merge: bump confidence + add evidence
            existing.observation_count += 1
            existing.confidence = min(0.9, existing.confidence + 0.1)  # Cap at 0.9
            existing.evidence.append(evidence[:200])
            existing.evidence = existing.evidence[-10:]  # Keep last 10
            existing.updated_at = now
            # Auto-promote to global if confidence >= 0.7
            if existing.confidence >= 0.7 and existing.scope == "project":
                existing.scope = "global"
                logger.info(
                    "[instinct] Promoted to global: %s (confidence=%.1f)",
                    existing.trigger[:60],
                    existing.confidence,
                )
            self.save(existing)
            return existing

        # Create new
        instinct_id = make_instinct_id(trigger, action)
        instinct = Instinct(
            id=instinct_id,
            trigger=trigger,
            action=action,
            confidence=0.3,
            evidence=[evidence[:200]],
            scope=scope,
            project_hash=self._project_hash,
            tags=tags,
            created_at=now,
            updated_at=now,
            observation_count=1,
        )
        self.save(instinct)
        logger.info(
            "[instinct] New: %s → %s (scope=%s)",
            trigger[:40],
            action[:40],
            scope,
        )
        return instinct

    def count(self, scope: str | None = None) -> int:
        """Count instincts."""
        return len(self.list_all(scope))

    def prune_stale(self, max_age_days: int = 90, min_confidence: float = 0.3) -> int:
        """Remove stale low-confidence instincts. Returns count removed."""
        now = datetime.now(UTC)
        removed = 0

        for d in [self._project_dir, self._global_dir]:
            if d is None or not d.exists():
                continue
            for path in d.glob("instinct_*.json"):
                if ".provenance" in path.name:
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    instinct = Instinct.from_dict(data)
                    updated = datetime.fromisoformat(instinct.updated_at)
                    age_days = (now - updated).days
                    if age_days > max_age_days and instinct.confidence < min_confidence:
                        path.unlink()
                        prov = path.with_suffix(".provenance.json")
                        if prov.exists():
                            prov.unlink()
                        removed += 1
                except Exception:
                    pass

        return removed

    def get_evolution_candidates(self, min_confidence: float = 0.9) -> list[Instinct]:
        """Get instincts ready to evolve into skills."""
        return [
            i
            for i in self.list_all()
            if i.confidence >= min_confidence and i.observation_count >= 5
        ]
