"""EloPhantoHub — skill registry client.

Connects to a GitHub-based skill registry (index.json) to search,
install, update, and publish skills. The agent can also use this
to auto-discover skills when no local match is found.

Registry format:
    index.json — master skill index
    skills/<name>/metadata.json — per-skill metadata
    skills/<name>/SKILL.md — skill content
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/elophanto/elophantohub/main/index.json"
)


@dataclass
class HubSkill:
    """A skill from the EloPhantoHub registry."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    url: str = ""
    elophanto_version: str = ""
    license: str = "MIT"


class HubClient:
    """Client for EloPhantoHub skill registry."""

    def __init__(
        self,
        skills_dir: Path,
        index_url: str = _DEFAULT_INDEX_URL,
        cache_dir: Path | None = None,
        cache_ttl_hours: int = 6,
    ) -> None:
        self._skills_dir = skills_dir
        self._index_url = index_url
        self._cache_dir = cache_dir or (skills_dir.parent / ".hub_cache")
        self._cache_ttl_hours = cache_ttl_hours

        self._index: list[HubSkill] = []
        self._index_loaded = False
        self._installed_from_hub: dict[str, str] = {}  # name → version

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_installed_manifest()

    async def refresh_index(self) -> int:
        """Fetch the registry index. Returns skill count."""
        cache_path = self._cache_dir / "index.json"

        # Check cache freshness
        if cache_path.exists():
            age_hours = (
                datetime.now(timezone.utc).timestamp() - cache_path.stat().st_mtime
            ) / 3600
            if age_hours < self._cache_ttl_hours:
                self._load_cached_index(cache_path)
                if self._index:
                    return len(self._index)

        # Fetch from remote
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self._index_url)
                resp.raise_for_status()
                data = resp.json()

            # Cache it
            cache_path.write_text(json.dumps(data, indent=2))

            self._index = [
                HubSkill(
                    name=s["name"],
                    description=s.get("description", ""),
                    version=s.get("version", "1.0.0"),
                    author=s.get("author", ""),
                    tags=s.get("tags", []),
                    downloads=s.get("downloads", 0),
                    url=s.get("url", ""),
                )
                for s in data.get("skills", [])
            ]
            self._index_loaded = True
            logger.info("EloPhantoHub index: %d skills", len(self._index))
            return len(self._index)

        except Exception as e:
            logger.debug("Failed to fetch EloPhantoHub index: %s", e)
            # Try cache even if stale
            if cache_path.exists():
                self._load_cached_index(cache_path)
            return len(self._index)

    def _load_cached_index(self, path: Path) -> None:
        """Load index from local cache."""
        try:
            data = json.loads(path.read_text())
            self._index = [
                HubSkill(
                    name=s["name"],
                    description=s.get("description", ""),
                    version=s.get("version", "1.0.0"),
                    author=s.get("author", ""),
                    tags=s.get("tags", []),
                    downloads=s.get("downloads", 0),
                    url=s.get("url", ""),
                )
                for s in data.get("skills", [])
            ]
            self._index_loaded = True
        except Exception as e:
            logger.warning("Failed to load cached index: %s", e)

    async def search(
        self, query: str, tags: list[str] | None = None
    ) -> list[HubSkill]:
        """Search the registry for matching skills."""
        if not self._index_loaded:
            await self.refresh_index()

        query_lower = query.lower()
        query_words = query_lower.split()
        results: list[tuple[float, HubSkill]] = []

        for skill in self._index:
            score = 0.0

            # Name match
            if query_lower in skill.name.lower():
                score += 3.0
            # Description match
            if query_lower in skill.description.lower():
                score += 1.0
            # Word matches
            for word in query_words:
                if word in skill.name.lower():
                    score += 2.0
                if word in skill.description.lower():
                    score += 0.5
                if word in [t.lower() for t in skill.tags]:
                    score += 1.5

            # Tag filter
            if tags:
                tag_match = any(
                    t.lower() in [st.lower() for st in skill.tags] for t in tags
                )
                if not tag_match:
                    continue

            if score > 0:
                results.append((score, skill))

        results.sort(key=lambda x: (-x[0], -x[1].downloads))
        return [s for _, s in results[:10]]

    async def install(self, name: str, version: str = "latest") -> str:
        """Install a skill from the hub. Returns installed name."""
        if not self._index_loaded:
            await self.refresh_index()

        # Find skill in index
        skill = next((s for s in self._index if s.name == name), None)
        if not skill:
            raise ValueError(f"Skill '{name}' not found in EloPhantoHub")

        if not skill.url:
            raise ValueError(f"Skill '{name}' has no download URL")

        # Download SKILL.md
        skill_dir = self._skills_dir / name
        if skill_dir.exists():
            raise FileExistsError(f"Skill '{name}' already installed")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Try fetching SKILL.md from the URL
                skill_md_url = f"{skill.url}/SKILL.md"
                resp = await client.get(skill_md_url)
                resp.raise_for_status()
                skill_content = resp.text

                # Try fetching metadata.json
                metadata = {"name": name, "version": skill.version, "source": "elophantohub"}
                try:
                    meta_resp = await client.get(f"{skill.url}/metadata.json")
                    if meta_resp.status_code == 200:
                        metadata = meta_resp.json()
                except Exception:
                    pass

            # Write to skills directory
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(skill_content)
            (skill_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2)
            )

            # Track as hub-installed
            self._installed_from_hub[name] = skill.version
            self._save_installed_manifest()

            logger.info("Installed skill '%s' v%s from EloPhantoHub", name, skill.version)
            return name

        except FileExistsError:
            raise
        except Exception as e:
            # Cleanup on failure
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            raise RuntimeError(f"Failed to install '{name}': {e}") from e

    async def update(self, name: str | None = None) -> list[str]:
        """Update hub-installed skills. None = update all. Returns updated names."""
        if not self._index_loaded:
            await self.refresh_index()

        targets = [name] if name else list(self._installed_from_hub.keys())
        updated: list[str] = []

        for skill_name in targets:
            current_version = self._installed_from_hub.get(skill_name)
            if not current_version:
                continue

            hub_skill = next(
                (s for s in self._index if s.name == skill_name), None
            )
            if not hub_skill or hub_skill.version == current_version:
                continue

            # Remove old and reinstall
            skill_dir = self._skills_dir / skill_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            del self._installed_from_hub[skill_name]

            try:
                await self.install(skill_name)
                updated.append(skill_name)
            except Exception as e:
                logger.warning("Failed to update '%s': %s", skill_name, e)

        return updated

    async def suggest(self, task_description: str) -> list[HubSkill]:
        """Suggest hub skills based on a task description.

        Used by the planner to auto-discover relevant skills.
        """
        return await self.search(task_description)

    def list_installed(self) -> list[dict[str, str]]:
        """List skills installed from the hub."""
        return [
            {"name": name, "version": version}
            for name, version in self._installed_from_hub.items()
        ]

    def _load_installed_manifest(self) -> None:
        """Load the manifest of hub-installed skills."""
        path = self._cache_dir / "installed.json"
        if path.exists():
            try:
                self._installed_from_hub = json.loads(path.read_text())
            except Exception:
                self._installed_from_hub = {}

    def _save_installed_manifest(self) -> None:
        """Persist the manifest of hub-installed skills."""
        path = self._cache_dir / "installed.json"
        path.write_text(json.dumps(self._installed_from_hub, indent=2))
