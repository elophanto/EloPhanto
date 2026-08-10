"""Agent packages — a whole configured agent as one shareable artifact.

A working agent is not just code: it is a persona, a set of skills, some
plugins, MCP servers, scheduled work, and the config that ties them
together. Today that lives scattered across a machine, which makes "give
me the setup you use for client outreach" an afternoon of copying files
and a "works on my machine" ending.

A **package** is that whole configuration expressed as one directory with
a ``PHANTO.md`` manifest at its root. Export one, hand it to someone,
import it, and they have the agent — not a README describing it.

    ---
    name: outreach-assistant
    version: 1.0.0
    author: Petr Royce
    skills: [api-playbook, booking-flows, prospecting-outreach]
    plugins: [replicate_generate]
    mcp_servers:
      linear: {transport: stdio, command: linear-mcp}
    schedules:
      - {name: morning-brief, cron: "0 8 * * *", goal: "Summarise overnight replies"}
    requires:
      credentials: [gmail]
      tools: [http_request]
    ---

    The prose body becomes the agent's persona brief.

Two safety properties, both learned from what package managers get wrong:

* **Import is inert until confirmed.** Nothing installs, no schedule
  arms, no MCP server launches until the operator approves the plan. A
  manifest is a *request*, and it arrives from someone else's machine.
* **Declared requirements are checked, not assumed.** A package that
  needs a credential the operator does not have should say so at import
  time, not fail three days later inside a cron job.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "PHANTO.md"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PackageError(Exception):
    """Raised when a package cannot be read, validated, or installed."""


@dataclass
class ScheduleSpec:
    """One scheduled job a package wants to create."""

    name: str
    goal: str
    cron: str = ""
    interval_seconds: int = 0

    def describe(self) -> str:
        when = self.cron or f"every {self.interval_seconds}s"
        return f"{self.name} ({when}): {self.goal}"


@dataclass
class AgentPackage:
    """A parsed ``PHANTO.md`` and the directory it came from."""

    name: str
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    persona: str = ""  # the manifest body
    skills: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedules: list[ScheduleSpec] = field(default_factory=list)
    required_credentials: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    source_dir: Path | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "skills": self.skills,
            "plugins": self.plugins,
            "mcp_servers": sorted(self.mcp_servers),
            "schedules": [s.describe() for s in self.schedules],
            "requires_credentials": self.required_credentials,
            "requires_tools": self.required_tools,
        }

    def render_plan(self, missing: dict[str, list[str]] | None = None) -> str:
        """Human-readable install plan, shown before anything is applied."""
        lines = [
            f"Package: {self.name} v{self.version}"
            + (f" by {self.author}" if self.author else ""),
        ]
        if self.description:
            lines.append(f"  {self.description}")
        lines.append("")
        lines.append("Will install:")
        lines.append(f"  skills   : {', '.join(self.skills) or '(none)'}")
        lines.append(f"  plugins  : {', '.join(self.plugins) or '(none)'}")
        lines.append(f"  MCP      : {', '.join(sorted(self.mcp_servers)) or '(none)'}")
        if self.schedules:
            lines.append("  schedules:")
            lines.extend(f"    - {s.describe()}" for s in self.schedules)
        else:
            lines.append("  schedules: (none)")
        if self.persona:
            first = self.persona.strip().splitlines()[0][:80]
            lines.append(f"  persona  : {first}…")

        unmet = {k: v for k, v in (missing or {}).items() if v}
        if unmet:
            lines.append("")
            lines.append("Unmet requirements:")
            lines.extend(
                f"  {kind}: {', '.join(items)}" for kind, items in unmet.items()
            )
        return "\n".join(lines)


# ── parsing ─────────────────────────────────────────────────────────


def parse_manifest(path: str | Path) -> AgentPackage:
    """Parse a ``PHANTO.md`` into an :class:`AgentPackage`."""
    manifest = Path(path)
    if manifest.is_dir():
        manifest = manifest / MANIFEST_NAME
    if not manifest.exists():
        raise PackageError(f"No {MANIFEST_NAME} at {manifest}")

    content = manifest.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if not match:
        raise PackageError(
            f"{manifest} has no YAML frontmatter block. A package manifest "
            "must start with '---' and close with '---'."
        )

    try:
        import yaml

        meta = yaml.safe_load(match.group(1)) or {}
    except Exception as exc:
        raise PackageError(f"{manifest} frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise PackageError(f"{manifest} frontmatter must be a mapping.")

    name = str(meta.get("name", "") or "").strip()
    if not name:
        raise PackageError(f"{manifest} is missing a 'name'.")

    version = str(meta.get("version", "0.1.0") or "0.1.0")
    if not _VERSION_RE.match(version):
        raise PackageError(
            f"{manifest}: version {version!r} must be semver (e.g. 1.0.0)."
        )

    schedules: list[ScheduleSpec] = []
    for entry in meta.get("schedules") or []:
        if not isinstance(entry, dict) or not entry.get("goal"):
            continue
        schedules.append(
            ScheduleSpec(
                name=str(entry.get("name", "") or "unnamed"),
                goal=str(entry["goal"]),
                cron=str(entry.get("cron", "") or ""),
                interval_seconds=int(entry.get("interval_seconds", 0) or 0),
            )
        )

    requires = meta.get("requires") or {}
    if not isinstance(requires, dict):
        requires = {}

    return AgentPackage(
        name=name,
        version=version,
        author=str(meta.get("author", "") or ""),
        description=str(meta.get("description", "") or ""),
        persona=match.group(2).strip(),
        skills=[str(s) for s in (meta.get("skills") or [])],
        plugins=[str(p) for p in (meta.get("plugins") or [])],
        mcp_servers={
            str(k): dict(v or {}) for k, v in (meta.get("mcp_servers") or {}).items()
        },
        schedules=schedules,
        required_credentials=[str(c) for c in (requires.get("credentials") or [])],
        required_tools=[str(t) for t in (requires.get("tools") or [])],
        source_dir=manifest.parent,
    )


# ── validation ──────────────────────────────────────────────────────


def check_requirements(
    package: AgentPackage,
    *,
    available_tools: set[str] | None = None,
    available_credentials: set[str] | None = None,
) -> dict[str, list[str]]:
    """Report which declared requirements this host cannot satisfy.

    Returns a dict of ``{kind: [missing...]}``; empty values mean satisfied.
    Checked before install so a package fails loudly at import rather than
    quietly at 3am inside a scheduled job.
    """
    missing: dict[str, list[str]] = {"tools": [], "credentials": [], "skills": []}
    if available_tools is not None:
        missing["tools"] = [
            t for t in package.required_tools if t not in available_tools
        ]
    if available_credentials is not None:
        missing["credentials"] = [
            c for c in package.required_credentials if c not in available_credentials
        ]
    if package.source_dir is not None:
        bundled = package.source_dir / "skills"
        for skill in package.skills:
            if not (bundled / skill).exists():
                missing["skills"].append(skill)
    return missing


# ── export ──────────────────────────────────────────────────────────


def export_package(
    destination: str | Path,
    *,
    name: str,
    version: str = "0.1.0",
    author: str = "",
    description: str = "",
    persona: str = "",
    skills: list[str] | None = None,
    plugins: list[str] | None = None,
    mcp_servers: dict[str, dict[str, Any]] | None = None,
    schedules: list[ScheduleSpec] | None = None,
    required_credentials: list[str] | None = None,
    required_tools: list[str] | None = None,
    project_root: Path | None = None,
) -> Path:
    """Write a package directory, copying in the named skills and plugins.

    Credentials are *never* copied — only the fact that the package needs
    a slug by that name. Shipping a package that carries live secrets is
    exactly the accident this design refuses to make possible.
    """
    import yaml

    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    source_root = project_root or Path.cwd()

    copied_skills: list[str] = []
    for skill in skills or []:
        src = source_root / "skills" / skill
        if not src.exists():
            logger.warning("Skill %r not found; skipping", skill)
            continue
        shutil.copytree(src, root / "skills" / skill, dirs_exist_ok=True)
        copied_skills.append(skill)

    copied_plugins: list[str] = []
    for plugin in plugins or []:
        src = source_root / "plugins" / plugin
        if not src.exists():
            logger.warning("Plugin %r not found; skipping", plugin)
            continue
        shutil.copytree(src, root / "plugins" / plugin, dirs_exist_ok=True)
        copied_plugins.append(plugin)

    meta: dict[str, Any] = {
        "name": name,
        "version": version,
        "author": author,
        "description": description,
        "exported_at": datetime.now(UTC).isoformat(),
        "skills": copied_skills,
        "plugins": copied_plugins,
    }
    if mcp_servers:
        meta["mcp_servers"] = mcp_servers
    if schedules:
        meta["schedules"] = [
            {
                "name": s.name,
                "goal": s.goal,
                **({"cron": s.cron} if s.cron else {}),
                **(
                    {"interval_seconds": s.interval_seconds}
                    if s.interval_seconds
                    else {}
                ),
            }
            for s in schedules
        ]
    requires: dict[str, Any] = {}
    if required_credentials:
        requires["credentials"] = required_credentials
    if required_tools:
        requires["tools"] = required_tools
    if requires:
        meta["requires"] = requires

    body = persona.strip() or f"# {name}\n\nDescribe how this agent should behave."
    manifest = (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body
        + "\n"
    )
    (root / MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    logger.info(
        "Exported package %s v%s to %s (%d skills, %d plugins)",
        name,
        version,
        root,
        len(copied_skills),
        len(copied_plugins),
    )
    return root / MANIFEST_NAME


# ── import ──────────────────────────────────────────────────────────


def install_package(
    package: AgentPackage,
    *,
    project_root: Path,
    install_skills: bool = True,
    install_plugins: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy a package's skills and plugins into the project.

    MCP servers and schedules are *reported*, not applied: both execute
    code on the operator's machine on someone else's schedule, so they
    stay a deliberate second step rather than a side effect of import.
    """
    if package.source_dir is None:
        raise PackageError("Package has no source directory to install from.")

    report: dict[str, Any] = {
        "skills_installed": [],
        "plugins_installed": [],
        "mcp_servers_to_add": sorted(package.mcp_servers),
        "schedules_to_create": [s.describe() for s in package.schedules],
        "dry_run": dry_run,
    }

    if install_skills:
        for skill in package.skills:
            src = package.source_dir / "skills" / skill
            if not src.exists():
                continue
            if not dry_run:
                shutil.copytree(
                    src, project_root / "skills" / skill, dirs_exist_ok=True
                )
            report["skills_installed"].append(skill)

    if install_plugins:
        for plugin in package.plugins:
            src = package.source_dir / "plugins" / plugin
            if not src.exists():
                continue
            if not dry_run:
                shutil.copytree(
                    src, project_root / "plugins" / plugin, dirs_exist_ok=True
                )
            report["plugins_installed"].append(plugin)

    if not dry_run:
        record = project_root / "data" / "installed_packages.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = (
                json.loads(record.read_text(encoding="utf-8"))
                if record.exists()
                else {}
            )
        except Exception:
            existing = {}
        existing[package.name] = {
            "version": package.version,
            "author": package.author,
            "installed_at": datetime.now(UTC).isoformat(),
            "skills": report["skills_installed"],
            "plugins": report["plugins_installed"],
        }
        record.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    return report
