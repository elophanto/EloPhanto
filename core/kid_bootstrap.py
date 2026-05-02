"""Kid-side bootstrap — runs INSIDE the kid container.

The kid is launched by Dockerfile.kid's CMD. On boot it:

1. Reads its identity from env (ELOPHANTO_KID_ID / KID_NAME / PURPOSE /
   PARENT_GATEWAY).
2. Parses KID_VAULT_JSON (plaintext-in-env subset of parent's vault),
   maps each key into the in-memory Config, then **clears** the env var
   so /proc/<pid>/environ exposure is bounded to a few seconds at boot.
3. Builds a minimal Config (kid mode disables organization, kids,
   swarm, autonomous_mind, payments — and the parent registry filter
   strips the matching tools).
4. Constructs an `Agent` using that config.
5. Connects to the parent's gateway as a CHILD_TASK_ASSIGNED listener.
6. For each task, runs `agent.run(task)` and sends the response back
   via gateway chat message addressed to the parent.

This is what makes a kid actually useful — without this, the kid would
boot, register, and idle forever.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# Env vars the kid uses on boot. Cleared from os.environ once consumed.
_VAULT_ENV = "KID_VAULT_JSON"
_KID_ID_ENV = "ELOPHANTO_KID_ID"
_KID_NAME_ENV = "ELOPHANTO_KID_NAME"
_PURPOSE_ENV = "KID_PURPOSE"
_GATEWAY_ENV = "ELOPHANTO_PARENT_GATEWAY"


def _consume_vault_env() -> dict[str, str]:
    """Parse and CLEAR the KID_VAULT_JSON env var.

    Returns the scoped dict of secrets. After this call, the env var is
    gone from os.environ — bounds the time it lives in /proc/<pid>/environ
    to whatever happened before this call.

    Empty / missing / malformed → returns empty dict (no crash).
    """
    raw = os.environ.pop(_VAULT_ENV, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning("KID_VAULT_JSON did not decode to a dict; ignoring")
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError as e:
        logger.warning("KID_VAULT_JSON malformed: %s; ignoring", e)
        return {}


def build_kid_config(
    vault_subset: dict[str, str],
    project_root: Path | None = None,
):
    """Build a minimal in-memory Config for kid execution.

    Deliberately disables features kids must not have:
    - gateway (server) — kid is a CLIENT, not server
    - organization — kids don't run their own org
    - kids — depth=1 (also enforced by registry filter)
    - swarm — kids don't spawn external coding agents
    - autonomous_mind — kid is task-driven, not autonomous
    - payments — kids never move money
    - heartbeat — kids don't run scheduled work

    Vault keys from `vault_subset` are mapped into the matching provider
    api_key field. Unknown keys are silently ignored.
    """
    from core.config import (
        Config,
        DatabaseConfig,
        IdentityConfig,
        KidConfig,
        KnowledgeConfig,
        LLMConfig,
        OrganizationConfig,
        PaymentsConfig,
        ProviderConfig,
        SwarmConfig,
    )

    project_root = project_root or Path.cwd()

    # Build provider configs from the vault subset. The kid trusts that
    # whatever the parent granted is what it needs.
    providers: dict[str, ProviderConfig] = {}
    for name in ("openrouter", "openai", "huggingface", "kimi", "zai"):
        if name in vault_subset:
            providers[name] = ProviderConfig(
                api_key=vault_subset[name],
                enabled=True,
            )
    # Codex is auth-file-based, not key-based. If the kid has it (via
    # bind-mounted ~/.codex/auth.json — not enabled by default), it
    # would auto-detect. For v1 kids skip codex entirely.
    if not providers:
        # No provider granted — kid will still boot, but llm_call fails.
        # Better to fail loudly than silently use a default.
        logger.warning(
            "Kid has no LLM provider keys in vault subset. "
            "LLM-dependent tools will fail."
        )

    llm_config = LLMConfig(
        providers=providers,
        provider_priority=list(providers.keys()),
    )

    # Minimal config — only what a kid needs.
    config = Config(
        llm=llm_config,
        database=DatabaseConfig(db_path=str(project_root / "kid.db")),
        knowledge=KnowledgeConfig(
            knowledge_dir=str(project_root / "knowledge"),
        ),
        identity=IdentityConfig(enabled=False),  # kids don't evolve identity
        organization=OrganizationConfig(enabled=False),
        kids=KidConfig(enabled=False),  # depth=1
        swarm=SwarmConfig(enabled=False),
        payments=PaymentsConfig(enabled=False),
        project_root=project_root,
    )
    # Disable other always-on features when present
    for attr_name in ("autonomous_mind", "heartbeat", "gateway"):
        sub = getattr(config, attr_name, None)
        if sub is not None and hasattr(sub, "enabled"):
            sub.enabled = False
    return config


async def kid_main() -> int:
    """Main entry point for the kid container's CMD.

    Returns process exit code.
    """
    logging.basicConfig(
        level=os.environ.get("ELOPHANTO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if os.environ.get("ELOPHANTO_KID") != "true":
        logger.error("kid_bootstrap launched without ELOPHANTO_KID=true; refusing")
        return 1

    kid_id = os.environ.get(_KID_ID_ENV, "unknown")
    kid_name = os.environ.get(_KID_NAME_ENV, "kid")
    purpose = os.environ.get(_PURPOSE_ENV, "")
    gateway = os.environ.get(_GATEWAY_ENV, "")

    logger.info(
        "Kid boot: id=%s name=%s gateway=%s purpose=%s",
        kid_id,
        kid_name,
        gateway,
        purpose[:120],
    )

    # Step 1: consume + clear vault env IMMEDIATELY so the time the
    # plaintext lives in /proc/<pid>/environ is bounded.
    vault_subset = _consume_vault_env()
    logger.info("Kid vault subset consumed (%d keys; env cleared)", len(vault_subset))

    # Step 2: build minimal config
    workspace = Path(os.environ.get("KID_WORKSPACE", "/workspace"))
    workspace.mkdir(parents=True, exist_ok=True)
    config = build_kid_config(vault_subset, project_root=workspace)

    # Step 3: build Agent — the existing class. ELOPHANTO_KID=true env
    # triggers the registry filter to strip kid_/payment_/wallet_/polymarket_
    # tools and the planner to inject <kid_self>.
    from core.agent import Agent

    agent = Agent(config)
    try:
        await agent.initialize()
    except Exception as e:
        logger.exception("Kid agent.initialize() failed: %s", e)
        return 2

    # Step 4: connect to parent gateway and listen for tasks
    from channels.kid_agent_adapter import KidAgentAdapter

    adapter = KidAgentAdapter(agent=agent)
    try:
        await adapter.start()
    except KeyboardInterrupt:
        pass
    finally:
        await adapter.stop()
        await agent.shutdown()
    return 0


def main() -> None:
    """Synchronous wrapper for the entrypoint."""
    sys.exit(asyncio.run(kid_main()))


if __name__ == "__main__":
    main()
