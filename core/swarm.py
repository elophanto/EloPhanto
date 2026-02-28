"""Agent swarm orchestration — spawn, monitor, redirect, and stop external coding agents.

External agents (Claude Code, Codex, Gemini CLI, etc.) run in isolated git worktrees
inside tmux sessions. The SwarmManager handles the full lifecycle: worktree creation,
prompt enrichment from the knowledge vault, tmux launch, background monitoring
(PR status, CI status), completion detection, notifications, and cleanup.

Everything is controlled through conversation — the LLM calls swarm tools,
the SwarmManager does the rest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import AgentProfileConfig, SwarmConfig
from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.database import Database
    from core.gateway import Gateway
    from core.swarm_security import SwarmOutputReport

logger = logging.getLogger(__name__)


@dataclass
class SwarmAgent:
    """A running or completed external agent."""

    agent_id: str
    profile: str
    task: str
    branch: str
    worktree_path: str
    tmux_session: str
    status: str = "running"
    done_criteria: str = "pr_created"
    pr_url: str | None = None
    pr_number: int | None = None
    ci_status: str | None = None
    enriched_prompt: str = ""
    spawned_at: str = ""
    completed_at: str | None = None
    stopped_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SwarmManager:
    """Orchestrates external coding agents in isolated worktrees."""

    def __init__(
        self,
        db: Database,
        config: SwarmConfig,
        project_root: Path,
        gateway: Gateway | None = None,
    ) -> None:
        self._db = db
        self._config = config
        self._project_root = project_root
        self._gateway = gateway
        self._agents: dict[str, SwarmAgent] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self._knowledge_search_tool: Any = None  # Injected by agent.py
        self._last_spawn_times: dict[str, float] = {}  # profile → monotonic time
        self._output_reports: dict[str, Any] = {}  # agent_id → SwarmOutputReport

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_monitoring(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    @property
    def running_agents(self) -> list[SwarmAgent]:
        return [a for a in self._agents.values() if a.status == "running"]

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background monitor and reload persisted agents."""
        import shutil

        if not shutil.which("tmux"):
            raise RuntimeError(
                "tmux is required for agent swarm but is not installed. "
                "Install it with: brew install tmux"
            )
        if not shutil.which("git"):
            raise RuntimeError("git is required for agent swarm but is not installed")

        await self._reload_from_db()
        if not self.is_monitoring:
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(), name="swarm-monitor"
            )
            logger.info(
                "Swarm monitor started (interval=%ds, %d running agents)",
                self._config.monitor_interval_seconds,
                len(self.running_agents),
            )

    async def stop(self) -> None:
        """Stop the background monitor (does NOT stop running agents)."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._monitor_task = None
        logger.info("Swarm monitor stopped")

    # ── Agent Spawning ──────────────────────────────────────────────

    async def spawn(
        self,
        task: str,
        repo: str | None = None,
        profile_name: str | None = None,
        branch_name: str | None = None,
        extra_context: str = "",
    ) -> SwarmAgent:
        """Spawn a new external agent.

        1. Resolve target repo (current project, GitHub clone, or fresh dir)
        2. Create isolated working directory
        3. Enrich prompt with context
        4. Launch tmux session
        5. Persist to DB and broadcast event
        """
        if len(self.running_agents) >= self._config.max_concurrent_agents:
            raise RuntimeError(
                f"Max concurrent agents ({self._config.max_concurrent_agents}) reached. "
                f"Stop a running agent first."
            )

        profile_name = profile_name or self._auto_select_profile(task)

        # Spawn cooldown — prevent rapid-fire agent spawning
        import time as _time

        cooldown = self._config.spawn_cooldown_seconds
        if cooldown > 0 and profile_name in self._last_spawn_times:
            elapsed = _time.monotonic() - self._last_spawn_times[profile_name]
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed)
                raise RuntimeError(
                    f"Spawn cooldown: {remaining}s remaining for profile "
                    f"'{profile_name}'. Minimum {cooldown}s between spawns."
                )

        profile = self._config.profiles.get(profile_name)
        if not profile:
            available = ", ".join(self._config.profiles.keys()) or "none configured"
            raise ValueError(
                f"Unknown agent profile: {profile_name}. Available: {available}"
            )

        agent_id = uuid.uuid4().hex[:8]

        if not branch_name:
            slug = self._slugify(task)[:40]
            branch_name = f"swarm/{slug}-{agent_id}"

        # Resolve working directory based on repo parameter
        is_external = bool(repo)
        work_dir = await self._resolve_work_dir(repo, branch_name, agent_id)

        enriched_prompt = await self._build_enriched_prompt(
            task, extra_context, profile, is_external=is_external
        )

        tmux_session = f"{self._config.tmux_session_prefix}-{agent_id}"
        await self._launch_tmux(tmux_session, work_dir, profile, enriched_prompt)

        agent = SwarmAgent(
            agent_id=agent_id,
            profile=profile_name,
            task=task,
            branch=branch_name,
            worktree_path=work_dir,
            tmux_session=tmux_session,
            done_criteria=profile.done_criteria or self._config.default_done_criteria,
            enriched_prompt=enriched_prompt,
            spawned_at=datetime.now(UTC).isoformat(),
        )

        self._agents[agent_id] = agent
        self._last_spawn_times[profile_name] = _time.monotonic()
        await self._persist_agent(agent)
        await self._log_activity(agent_id, "spawned", f"Profile: {profile_name}")

        await self._broadcast(
            EventType.AGENT_SPAWNED,
            {
                "agent_id": agent_id,
                "profile": profile_name,
                "task": task[:200],
                "branch": branch_name,
                "tmux_session": tmux_session,
            },
        )

        return agent

    # ── Agent Control ───────────────────────────────────────────────

    async def redirect(self, agent_id: str, instructions: str) -> bool:
        """Send new instructions to a running agent via tmux send-keys."""
        agent = self._agents.get(agent_id)
        if not agent or agent.status != "running":
            return False

        escaped = instructions.replace("'", "'\\''")
        cmd = f"tmux send-keys -t {agent.tmux_session} '{escaped}' Enter"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        await self._log_activity(agent_id, "redirected", instructions[:500])
        await self._broadcast(
            EventType.AGENT_REDIRECTED,
            {"agent_id": agent_id, "instructions": instructions[:200]},
        )
        return True

    async def stop_agent(self, agent_id: str, reason: str = "user request") -> bool:
        """Stop a running agent by killing its tmux session."""
        agent = self._agents.get(agent_id)
        if not agent or agent.status != "running":
            return False

        proc = await asyncio.create_subprocess_shell(
            f"tmux kill-session -t {agent.tmux_session}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        agent.status = "stopped"
        agent.stopped_reason = reason
        agent.completed_at = datetime.now(UTC).isoformat()
        await self._persist_agent(agent)
        await self._log_activity(agent_id, "stopped", reason)
        await self._broadcast(
            EventType.AGENT_STOPPED,
            {"agent_id": agent_id, "reason": reason},
        )
        return True

    async def get_status(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Get status of one or all agents."""
        if agent_id:
            agent = self._agents.get(agent_id)
            agents = [agent] if agent else []
        else:
            agents = sorted(
                self._agents.values(),
                key=lambda a: a.spawned_at,
                reverse=True,
            )

        results = []
        for agent in agents:
            tmux_alive = await self._is_tmux_alive(agent.tmux_session)
            results.append(
                {
                    "agent_id": agent.agent_id,
                    "profile": agent.profile,
                    "task": agent.task[:100],
                    "branch": agent.branch,
                    "worktree_path": agent.worktree_path,
                    "status": agent.status,
                    "tmux_alive": tmux_alive,
                    "pr_url": agent.pr_url,
                    "ci_status": agent.ci_status,
                    "spawned_at": agent.spawned_at,
                    "completed_at": agent.completed_at,
                    "security_verdict": (
                        report.verdict
                        if (report := self._output_reports.get(agent.agent_id))
                        else None
                    ),
                    "security_findings": (
                        report.findings[:5]
                        if (report := self._output_reports.get(agent.agent_id))
                        else []
                    ),
                }
            )
        return results

    # ── Profile Selection ───────────────────────────────────────────

    def _auto_select_profile(self, task: str) -> str:
        """Select the best agent profile based on task keywords vs strengths."""
        task_lower = task.lower()
        best_profile = ""
        best_score = -1

        for name, profile in self._config.profiles.items():
            score = sum(1 for s in profile.strengths if s.lower() in task_lower)
            # Bonus for explicit agent name mention
            if name.replace("-", " ") in task_lower or name in task_lower:
                score += 10
            if score > best_score:
                best_score = score
                best_profile = name

        if not best_profile and self._config.profiles:
            best_profile = next(iter(self._config.profiles))

        return best_profile

    # ── Working Directory Resolution ────────────────────────────────

    async def _resolve_work_dir(
        self, repo: str | None, branch_name: str, agent_id: str
    ) -> str:
        """Resolve the working directory for the agent.

        - ``None`` / empty → git worktree off current project (self-dev)
        - GitHub URL → clone into a unique directory
        - Local path → git worktree off that repo
        - ``"new"`` → create a fresh empty directory with ``git init``
        """
        if not repo:
            # Self-dev: worktree off current project
            return await self._create_worktree(branch_name)

        base_dir = self._config.worktree_base_dir
        if not base_dir:
            base_dir = str(self._project_root.parent / ".elophanto-worktrees")

        if repo.lower() == "new":
            # Fresh project — unique dir with git init
            slug = branch_name.replace("/", "-")
            work_dir = str(Path(base_dir) / f"{slug}-{agent_id}")
            await self._run_shell(f"mkdir -p {work_dir}")
            await self._run_shell(f"git -C {work_dir} init")
            return work_dir

        if repo.startswith("https://") or repo.startswith("git@"):
            # GitHub/remote URL — clone into unique dir
            repo_name = repo.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")
            work_dir = str(Path(base_dir) / f"{repo_name}-{agent_id}")
            proc = await asyncio.create_subprocess_shell(
                f"git clone {repo} {work_dir}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")
            # Create feature branch
            await self._run_shell(f"git -C {work_dir} checkout -b {branch_name}")
            return work_dir

        # Local path — create worktree off that repo
        local_repo = Path(repo).expanduser().resolve()
        if not (local_repo / ".git").exists():
            raise RuntimeError(f"Not a git repository: {repo}")
        return await self._create_worktree(branch_name, project_root=local_repo)

    async def _run_shell(self, cmd: str) -> tuple[int, str, str]:
        """Run a shell command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    # ── Git Worktree Management ─────────────────────────────────────

    async def _create_worktree(
        self, branch_name: str, project_root: Path | None = None
    ) -> str:
        """Create a git worktree on a new feature branch.

        The directory name always includes a unique suffix (from the branch name
        which contains the agent_id) so it never collides with existing dirs.

        Handles stale leftovers from previous runs:
        - Prunes dead worktree entries from git's tracking
        - Removes leftover directories that block creation
        - Falls back to an existing branch instead of ``-b`` if the branch exists
        """
        root = project_root or self._project_root

        base_dir = self._config.worktree_base_dir
        if not base_dir:
            if self._config.workspace_isolation:
                base_dir = "/tmp/elophanto/swarm"
            else:
                base_dir = str(root.parent / ".elophanto-worktrees")

        worktree_dir = branch_name.replace("/", "-")
        worktree_path = str(Path(base_dir) / worktree_dir)

        await self._run_shell(f"mkdir -p {base_dir}")

        # Prune stale worktree entries (e.g. from a crashed previous run)
        await self._run_shell(f"git -C {root} worktree prune")

        # If the directory already exists, remove it so git worktree add succeeds
        wt = Path(worktree_path)
        if wt.exists():
            logger.info("Removing stale worktree directory: %s", worktree_path)
            import shutil

            shutil.rmtree(worktree_path, ignore_errors=True)

        # Check if the branch already exists
        branch_exists = await self._branch_exists(branch_name, root)

        if branch_exists:
            cmd = f"git -C {root} worktree add {worktree_path} {branch_name}"
        else:
            cmd = f"git -C {root} worktree add -b {branch_name} {worktree_path}"

        rc, _, stderr = await self._run_shell(cmd)
        if rc != 0:
            raise RuntimeError(f"git worktree add failed: {stderr}")

        return worktree_path

    async def _branch_exists(
        self, branch_name: str, project_root: Path | None = None
    ) -> bool:
        """Check if a git branch already exists."""
        root = project_root or self._project_root
        rc, _, _ = await self._run_shell(
            f"git -C {root} rev-parse --verify {branch_name} 2>/dev/null"
        )
        return rc == 0

    async def _cleanup_worktree(self, agent: SwarmAgent) -> None:
        """Remove a worktree after its branch is merged."""
        try:
            proc = await asyncio.create_subprocess_shell(
                f"git -C {self._project_root} worktree remove "
                f"{agent.worktree_path} --force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            proc = await asyncio.create_subprocess_shell(
                f"git -C {self._project_root} branch -d {agent.branch}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            await self._log_activity(agent.agent_id, "cleanup", "worktree removed")
        except Exception as e:
            logger.debug("Worktree cleanup failed for %s: %s", agent.agent_id, e)

    # ── Prompt Enrichment ───────────────────────────────────────────

    async def _build_enriched_prompt(
        self,
        task: str,
        extra_context: str,
        profile: AgentProfileConfig,
        *,
        is_external: bool = False,
    ) -> str:
        """Build a context-enriched prompt for the external agent.

        When *is_external* is True the agent is working on a different repo
        (cloned or fresh), so we skip EloPhanto knowledge enrichment and adjust
        the PR instructions accordingly.
        """
        sections = [task]

        if extra_context:
            sections.append(f"\nAdditional context:\n{extra_context}")

        # Only inject EloPhanto knowledge for self-dev tasks
        if not is_external and self._config.prompt_enrichment:
            knowledge = await self._pull_knowledge_context(task)
            if knowledge:
                from core.swarm_security import sanitize_enrichment_context

                knowledge = sanitize_enrichment_context(knowledge)
                sections.append(f"\nRelevant project knowledge:\n{knowledge}")

        if is_external:
            sections.append(
                "\nYou are working in an isolated project directory on a feature branch. "
                "When done, commit your work and create a PR using `gh pr create`. "
                "Do NOT push to or create PRs against any other repository."
            )
        else:
            sections.append(
                "\nYou are working in a git worktree on a feature branch. "
                "Create a PR when done using `gh pr create`."
            )

        sections.append(
            "\nSECURITY CONSTRAINTS:\n"
            "- Do NOT access files outside your working directory\n"
            "- Do NOT read or modify vault, config.yaml, or .env files\n"
            "- Do NOT add new dependencies without documenting the reason"
        )

        return "\n".join(sections)

    async def _pull_knowledge_context(self, query: str) -> str:
        """Search knowledge base for relevant context chunks."""
        if not self._knowledge_search_tool:
            return ""
        try:
            result = await self._knowledge_search_tool.execute(
                {"query": query, "limit": self._config.max_enrichment_chunks}
            )
            if result.success and result.data.get("results"):
                chunks = result.data["results"]
                return "\n---\n".join(
                    f"[{c.get('source', 'unknown')}] {c.get('content', '')[:500]}"
                    for c in chunks
                )
        except Exception as e:
            logger.debug("Knowledge enrichment failed: %s", e)
        return ""

    # ── tmux Session Management ─────────────────────────────────────

    async def _launch_tmux(
        self,
        session_name: str,
        worktree_path: str,
        profile: AgentProfileConfig,
        prompt: str,
    ) -> None:
        """Launch an agent in a new tmux session.

        Supports two modes:
        - **Headless** (args contain ``-p``): The prompt is read from
          ``.elophanto-prompt.md`` via ``cat`` and piped as a CLI argument.
          No interactive acceptance prompts, no ``send-keys`` timing issues.
        - **Interactive** (legacy): The agent CLI starts first, then the
          prompt is sent via ``tmux send-keys`` after a short delay.
        """
        agent_cmd = profile.command
        args = list(profile.args)

        # Build isolated environment — strip sensitive vars
        from core.swarm_security import build_isolated_env

        safe_env = build_isolated_env(session_name, profile.env)
        env_str = " ".join(f"{k}={v}" for k, v in safe_env.items())
        env_prefix = f"{env_str} " if env_str else ""

        # Write prompt to file in worktree (used by both modes)
        prompt_file = Path(worktree_path) / ".elophanto-prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Detect headless mode: -p flag means prompt is a CLI argument
        is_headless = "-p" in args

        if is_headless:
            # Headless mode — embed prompt file read in the command.
            # This avoids interactive acceptance prompts entirely.
            # Remove -p from args; we'll reconstruct it with the prompt file.
            args_without_p = [a for a in args if a != "-p"]
            args_str = " ".join(args_without_p)
            prompt_path = str(prompt_file)
            # Use shell substitution to read prompt from file
            full_cmd = (
                f"{env_prefix}{agent_cmd} -p "
                f'"$(cat {prompt_path})" '
                f"{args_str}".strip()
            )
        else:
            # Interactive mode — start CLI, then send prompt via send-keys
            args_str = " ".join(args)
            full_cmd = f"{env_prefix}{agent_cmd} {args_str}".strip()

        # Create tmux session running the agent command
        tmux_cmd = (
            f"tmux new-session -d -s {session_name} " f"-c {worktree_path} '{full_cmd}'"
        )
        proc = await asyncio.create_subprocess_shell(
            tmux_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"tmux launch failed: {stderr.decode().strip()}")

        if not is_headless:
            # Interactive mode: give the agent CLI a moment to start,
            # then send the prompt via tmux send-keys
            await asyncio.sleep(2)
            escaped = prompt.replace("'", "'\\''")
            send_cmd = f"tmux send-keys -t {session_name} '{escaped}' Enter"
            proc = await asyncio.create_subprocess_shell(
                send_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

    async def _is_tmux_alive(self, session_name: str) -> bool:
        """Check if a tmux session is still running."""
        proc = await asyncio.create_subprocess_shell(
            f"tmux has-session -t {session_name} 2>/dev/null",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    # ── Background Monitor ──────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """Poll running agents for completion."""
        interval = self._config.monitor_interval_seconds
        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_agents()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Swarm monitor tick error", exc_info=True)

    async def _check_agents(self) -> None:
        """Check all running agents for completion criteria."""
        for agent in list(self.running_agents):
            try:
                await self._check_single_agent(agent)
            except Exception as e:
                logger.debug("Error checking agent %s: %s", agent.agent_id, e)

    async def _check_single_agent(self, agent: SwarmAgent) -> None:
        """Check if a single agent has met its done criteria."""
        alive = await self._is_tmux_alive(agent.tmux_session)

        # Check for PR
        pr_info = await self._check_pr_status(agent)
        if pr_info and pr_info.get("number"):
            agent.pr_url = pr_info.get("url", "")
            agent.pr_number = int(pr_info["number"])
            ci_status = await self._check_ci_status(agent.pr_number)
            agent.ci_status = ci_status

        # Output validation — scan PR diff for suspicious patterns
        if self._config.output_validation and agent.pr_url:
            from core.swarm_security import validate_agent_output

            report = await validate_agent_output(
                agent.agent_id, agent.branch, self._project_root
            )
            self._output_reports[agent.agent_id] = report

            if report.verdict == "blocked" and self._config.auto_block_suspicious:
                await self.stop_agent(
                    agent.agent_id,
                    f"security:blocked - {'; '.join(report.findings[:3])}",
                )
                await self._broadcast(
                    EventType.AGENT_SECURITY_ALERT,
                    {
                        "agent_id": agent.agent_id,
                        "findings": report.findings,
                        "verdict": report.verdict,
                    },
                )
                return

        # Evaluate done criteria
        done = False
        if agent.done_criteria == "pr_created" and agent.pr_url:
            done = True
        elif agent.done_criteria == "ci_passed" and agent.ci_status == "success":
            done = True

        # tmux died without meeting criteria = failure
        if not alive and not done:
            agent.status = "failed"
            agent.completed_at = datetime.now(UTC).isoformat()
            agent.stopped_reason = "tmux session exited without meeting done criteria"
            await self._persist_agent(agent)
            await self._log_activity(agent.agent_id, "failed", agent.stopped_reason)
            await self._broadcast(
                EventType.AGENT_FAILED,
                {
                    "agent_id": agent.agent_id,
                    "task": agent.task[:200],
                    "reason": agent.stopped_reason,
                    "worktree_path": agent.worktree_path,
                },
            )
            return

        if done:
            agent.status = "completed"
            agent.completed_at = datetime.now(UTC).isoformat()
            await self._persist_agent(agent)
            await self._log_activity(agent.agent_id, "completed", agent.pr_url or "")
            await self._broadcast(
                EventType.AGENT_COMPLETED,
                {
                    "agent_id": agent.agent_id,
                    "task": agent.task[:200],
                    "profile": agent.profile,
                    "pr_url": agent.pr_url,
                    "ci_status": agent.ci_status,
                    "branch": agent.branch,
                    "worktree_path": agent.worktree_path,
                },
            )
            if self._config.cleanup_merged_worktrees and agent.ci_status == "success":
                asyncio.create_task(self._cleanup_worktree(agent))
            return

        # Kill switch — timeout, diff size, blocked output
        profile = self._config.profiles.get(agent.profile)
        if profile:
            from core.swarm_security import check_kill_conditions

            kill_report: SwarmOutputReport | None = self._output_reports.get(
                agent.agent_id
            )
            should_kill, reason = check_kill_conditions(
                agent, profile, self._config, kill_report
            )
            if should_kill:
                await self.stop_agent(agent.agent_id, reason)
                return

        # Persist any status changes (pr_url, ci_status)
        await self._persist_agent(agent)

    async def _check_pr_status(self, agent: SwarmAgent) -> dict[str, Any] | None:
        """Check if a PR exists for this agent's branch."""
        cmd = f"gh pr list --head {agent.branch} --json number,url,state"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            prs = json.loads(stdout.decode())
            return prs[0] if prs else None
        except (json.JSONDecodeError, IndexError):
            return None

    async def _check_ci_status(self, pr_number: int) -> str:
        """Check CI status for a PR."""
        cmd = f"gh pr checks {pr_number} --json name,state"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return "unknown"
        try:
            checks = json.loads(stdout.decode())
            if not checks:
                return "pending"
            states = [c.get("state", "").lower() for c in checks]
            if all(s == "success" for s in states):
                return "success"
            if any(s == "failure" for s in states):
                return "failure"
            return "pending"
        except (json.JSONDecodeError, KeyError):
            return "unknown"

    # ── Persistence ─────────────────────────────────────────────────

    async def _persist_agent(self, agent: SwarmAgent) -> None:
        """Upsert agent to database."""
        await self._db.execute_insert(
            """INSERT INTO swarm_agents
               (agent_id, profile, task, branch, worktree_path, tmux_session,
                status, done_criteria, pr_url, pr_number, ci_status,
                enriched_prompt, spawned_at, completed_at, stopped_reason,
                metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 status=excluded.status, pr_url=excluded.pr_url,
                 pr_number=excluded.pr_number, ci_status=excluded.ci_status,
                 completed_at=excluded.completed_at,
                 stopped_reason=excluded.stopped_reason,
                 metadata_json=excluded.metadata_json""",
            (
                agent.agent_id,
                agent.profile,
                agent.task,
                agent.branch,
                agent.worktree_path,
                agent.tmux_session,
                agent.status,
                agent.done_criteria,
                agent.pr_url,
                agent.pr_number,
                agent.ci_status,
                agent.enriched_prompt,
                agent.spawned_at,
                agent.completed_at,
                agent.stopped_reason,
                json.dumps(agent.metadata),
            ),
        )

    async def _log_activity(self, agent_id: str, event: str, detail: str) -> None:
        """Insert into swarm_activity_log."""
        await self._db.execute_insert(
            "INSERT INTO swarm_activity_log (agent_id, event, detail, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (agent_id, event, detail, datetime.now(UTC).isoformat()),
        )

    async def _reload_from_db(self) -> None:
        """Reload running agents from database (for restart survival)."""
        rows = await self._db.execute(
            "SELECT * FROM swarm_agents WHERE status = 'running'"
        )
        for row in rows:
            agent = SwarmAgent(
                agent_id=row["agent_id"],
                profile=row["profile"],
                task=row["task"],
                branch=row["branch"],
                worktree_path=row["worktree_path"],
                tmux_session=row["tmux_session"],
                status=row["status"],
                done_criteria=row["done_criteria"],
                pr_url=row["pr_url"],
                pr_number=row["pr_number"],
                ci_status=row["ci_status"],
                enriched_prompt=row["enriched_prompt"] or "",
                spawned_at=row["spawned_at"],
                completed_at=row["completed_at"],
                stopped_reason=row["stopped_reason"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            self._agents[agent.agent_id] = agent
        if self._agents:
            logger.info("Reloaded %d running swarm agents from DB", len(self._agents))

    # ── Helpers ─────────────────────────────────────────────────────

    async def _broadcast(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Broadcast event to all connected channels."""
        if self._gateway:
            await self._gateway.broadcast(
                event_message("", event_type, data), session_id=None
            )
        else:
            logger.info("Swarm event [%s]: %s", event_type, data)

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a URL-safe slug for branch names."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[-\s]+", "-", text)
        return text.strip("-")
