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

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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
    author_tier: str = ""  # new, verified, trusted, official
    checksum: str = ""  # "sha256:<hex>"
    checksum_metadata: str = ""  # "sha256:<hex>" for metadata.json
    revoked: bool = False
    revoked_at: str = ""
    revoked_reason: str = ""


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
        self._installed_from_hub: dict[str, dict[str, str]] = {}  # name → info

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_installed_manifest()

    @staticmethod
    def _parse_hub_skill(s: dict) -> HubSkill:
        """Parse a single skill entry from index.json."""
        return HubSkill(
            name=s["name"],
            description=s.get("description", ""),
            version=s.get("version", "1.0.0"),
            author=s.get("author", ""),
            tags=s.get("tags", []),
            downloads=s.get("downloads", 0),
            url=s.get("url", ""),
            author_tier=s.get("author_tier", ""),
            checksum=s.get("checksum", ""),
            checksum_metadata=s.get("checksum_metadata", ""),
            revoked=s.get("revoked", False),
            revoked_at=s.get("revoked_at", ""),
            revoked_reason=s.get("revoked_reason", ""),
        )

    async def refresh_index(self) -> int:
        """Fetch the registry index. Returns skill count."""
        cache_path = self._cache_dir / "index.json"

        # Check cache freshness
        if cache_path.exists():
            age_hours = (
                datetime.now(UTC).timestamp() - cache_path.stat().st_mtime
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

            self._index = [self._parse_hub_skill(s) for s in data.get("skills", [])]
            self._index_loaded = True
            self._handle_revocations()
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
            self._index = [self._parse_hub_skill(s) for s in data.get("skills", [])]
            self._index_loaded = True
        except Exception as e:
            logger.warning("Failed to load cached index: %s", e)

    def _handle_revocations(self) -> None:
        """Check for revoked skills that are currently installed and quarantine them."""
        revoked_dir = self._skills_dir / "_revoked"
        for skill in self._index:
            if not skill.revoked:
                continue
            if skill.name not in self._installed_from_hub:
                continue

            logger.warning(
                "Skill '%s' has been REVOKED: %s",
                skill.name,
                skill.revoked_reason or "no reason given",
            )

            # Move to _revoked/ quarantine directory
            skill_dir = self._skills_dir / skill.name
            if skill_dir.exists():
                revoked_dir.mkdir(parents=True, exist_ok=True)
                dest = revoked_dir / skill.name
                if dest.exists():
                    shutil.rmtree(dest)
                skill_dir.rename(dest)

            # Remove from installed manifest
            del self._installed_from_hub[skill.name]
            self._save_installed_manifest()

    async def search(self, query: str, tags: list[str] | None = None) -> list[HubSkill]:
        """Search the registry for matching skills."""
        if not self._index_loaded:
            await self.refresh_index()

        query_lower = query.lower()
        query_words = query_lower.split()
        results: list[tuple[float, HubSkill]] = []

        for skill in self._index:
            if skill.revoked:
                continue

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

        if skill.revoked:
            raise ValueError(
                f"Skill '{name}' has been revoked: {skill.revoked_reason or 'no reason given'}"
            )

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

                # Verify SKILL.md checksum if registry provides one
                if skill.checksum:
                    expected = skill.checksum.removeprefix("sha256:")
                    actual = hashlib.sha256(skill_content.encode()).hexdigest()
                    if actual != expected:
                        raise ValueError(
                            f"Checksum mismatch for '{name}' SKILL.md: "
                            f"expected {expected[:12]}…, got {actual[:12]}…"
                        )

                # Try fetching metadata.json
                metadata: dict = {
                    "name": name,
                    "version": skill.version,
                    "source": "elophantohub",
                    "author_tier": skill.author_tier,
                }
                try:
                    meta_resp = await client.get(f"{skill.url}/metadata.json")
                    if meta_resp.status_code == 200:
                        meta_content = meta_resp.text
                        # Verify metadata checksum if available
                        if skill.checksum_metadata:
                            expected_meta = skill.checksum_metadata.removeprefix(
                                "sha256:"
                            )
                            actual_meta = hashlib.sha256(
                                meta_content.encode()
                            ).hexdigest()
                            if actual_meta != expected_meta:
                                raise ValueError(
                                    f"Checksum mismatch for '{name}' metadata.json"
                                )
                        metadata = json.loads(meta_content)
                except ValueError:
                    raise
                except Exception:
                    pass

            # Ensure author_tier flows through to metadata
            if "author_tier" not in metadata and skill.author_tier:
                metadata["author_tier"] = skill.author_tier

            # Write to skills directory
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(skill_content)
            (skill_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

            # Track as hub-installed with rich metadata
            content_hash = hashlib.sha256(skill_content.encode()).hexdigest()
            self._installed_from_hub[name] = {
                "version": skill.version,
                "checksum": f"sha256:{content_hash}",
                "author_tier": skill.author_tier,
                "installed_at": datetime.now(UTC).isoformat(),
            }
            self._save_installed_manifest()

            logger.info(
                "Installed skill '%s' v%s from EloPhantoHub", name, skill.version
            )
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
            info = self._installed_from_hub.get(skill_name)
            if not info:
                continue
            current_version = (
                info.get("version", "") if isinstance(info, dict) else info
            )

            hub_skill = next((s for s in self._index if s.name == skill_name), None)
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
        results = []
        for name, info in self._installed_from_hub.items():
            if isinstance(info, dict):
                results.append({"name": name, **info})
            else:
                # Backward compat: old format was name → version string
                results.append({"name": name, "version": info})
        return results

    def _load_installed_manifest(self) -> None:
        """Load the manifest of hub-installed skills.

        Supports both old format (name → version string) and new format
        (name → {version, checksum, author_tier, installed_at}).
        """
        path = self._cache_dir / "installed.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                # Migrate old format entries
                migrated: dict[str, dict[str, str]] = {}
                for name, value in raw.items():
                    if isinstance(value, str):
                        migrated[name] = {"version": value}
                    else:
                        migrated[name] = value
                self._installed_from_hub = migrated
            except Exception:
                self._installed_from_hub = {}

    def _save_installed_manifest(self) -> None:
        """Persist the manifest of hub-installed skills."""
        path = self._cache_dir / "installed.json"
        path.write_text(json.dumps(self._installed_from_hub, indent=2))
