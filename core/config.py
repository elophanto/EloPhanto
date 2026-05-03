"""Configuration system for EloPhanto.

Loads config.yaml, validates required fields, and provides typed access.
Supports environment variable overrides for API keys.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    api_key: str = ""
    enabled: bool = False
    base_url: str = ""
    # Z.ai-specific
    coding_plan: bool = False
    base_url_coding: str = ""
    base_url_paygo: str = ""
    default_model: str = ""
    # Tool profile limits
    max_tools: int = 0  # 0 = no limit
    tool_deny: list[str] = field(default_factory=list)  # groups to exclude


@dataclass
class RoutingConfig:
    """Per-task-type routing preferences."""

    preferred_provider: str = ""
    models: dict[str, str] = field(default_factory=dict)  # provider -> model
    tool_profile: str = ""  # override profile for this task type
    local_only: bool = False
    # Reasoning effort for OpenRouter / OpenAI models that support thinking tokens.
    # Values: "xhigh", "high", "medium", "low", "minimal", "none", or "" (omit field).
    reasoning_effort: str = ""
    # Legacy fields — still parsed for backward compat with old configs
    preferred_model: str = ""
    fallback_provider: str = ""
    fallback_model: str = ""
    local_fallback: str = ""


@dataclass
class BudgetConfig:
    """Budget limits for LLM spending."""

    daily_limit_usd: float = 10.0
    per_task_limit_usd: float = 2.0


@dataclass
class LLMConfig:
    """All LLM-related configuration."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    provider_priority: list[str] = field(default_factory=list)
    routing: dict[str, RoutingConfig] = field(default_factory=dict)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    tool_profiles: dict[str, list[str]] = field(default_factory=dict)
    # OpenRouter model slug used when messages contain image_url blocks.
    # Empty = strip images and use normal routing (Z.ai already does this).
    vision_model: str = ""


@dataclass
class ShellConfig:
    """Shell execution configuration."""

    timeout: int = 30
    blacklist_patterns: list[str] = field(default_factory=list)
    safe_commands: list[str] = field(default_factory=list)
    max_concurrent_processes: int = 10


@dataclass
class KnowledgeConfig:
    """Knowledge base configuration."""

    knowledge_dir: str = "knowledge"
    embedding_provider: str = "auto"  # "auto", "openrouter", or "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_fallback: str = "mxbai-embed-large"
    embedding_openrouter_model: str = "google/gemini-embedding-001"
    embedding_dimensions: int = 768
    chunk_max_tokens: int = 1000
    chunk_min_tokens: int = 50
    search_top_k: int = 5
    auto_index_on_startup: bool = True


@dataclass
class DatabaseConfig:
    """Database configuration."""

    db_path: str = "data/elophanto.db"


@dataclass
class PluginConfig:
    """Plugin system configuration."""

    plugins_dir: str = "plugins"
    auto_load: bool = True


@dataclass
class SelfDevConfig:
    """Self-development pipeline configuration."""

    max_llm_calls: int = 50
    max_time_seconds: int = 1800
    max_retries: int = 3
    test_timeout: int = 60
    review_model_override: str = ""


@dataclass
class BrowserConfig:
    """Browser automation configuration (Playwright+CDP)."""

    enabled: bool = False
    mode: str = "fresh"  # fresh | direct | profile | cdp_port | cdp_ws
    headless: bool = False
    cdp_port: int = 9222
    cdp_ws_endpoint: str = ""
    user_data_dir: str = ""
    profile_directory: str = (
        "Default"  # Chrome profile subdir (Default, Profile 1, etc.)
    )
    use_system_chrome: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    vision_model: str = "google/gemini-2.0-flash-001"
    profile_refresh_hours: float = (
        8.0  # 0 = never auto-refresh (agent sessions persist)
    )


@dataclass
class DesktopConfig:
    """Desktop GUI automation configuration."""

    enabled: bool = False
    mode: str = "local"  # local | remote
    vm_ip: str = ""  # required for remote mode
    server_port: int = 5000
    screen_width: int = 1920
    screen_height: int = 1080
    observation_type: str = (
        "screenshot"  # screenshot | a11y_tree | screenshot_a11y_tree
    )
    max_steps: int = 15
    sleep_after_action: float = 1.0


@dataclass
class SchedulerConfig:
    """Background scheduling configuration."""

    enabled: bool = False
    max_concurrent_tasks: int = 1
    default_max_retries: int = 3
    task_timeout_seconds: int = 600


@dataclass
class GatewayConfig:
    """WebSocket gateway configuration."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 18789
    auth_token_ref: str = ""
    max_sessions: int = 50
    session_timeout_hours: int = 24
    unified_sessions: bool = True  # All channels share one conversation

    # ── TLS (cross-machine peer connections) ─────────────────────────
    # When both `tls_cert` and `tls_key` are set, the gateway listens
    # with wss:// instead of ws://. Strongly recommended when binding
    # beyond loopback. Self-signed certs work; for peers to trust them
    # without warnings, use a CA-signed cert (Let's Encrypt via Caddy
    # is the easy path) or run inside Tailscale (which encrypts at the
    # WireGuard layer regardless).
    tls_cert: str = ""  # path to PEM cert chain
    tls_key: str = ""  # path to PEM private key

    # ── Peer identity enforcement ────────────────────────────────────
    # When True, the gateway refuses CHAT/COMMAND from clients that
    # haven't completed the IDENTIFY handshake within `verify_grace_seconds`
    # of connecting. Loopback connections (127.0.0.1, ::1) are always
    # exempt — your local CLI/Web/VSCode adapters don't need to speak
    # IDENTIFY because they're already on your machine. Critical for
    # any setup that binds beyond loopback: flips the security model
    # from "URL+token = trusted" to "verified-identity-only."
    require_verified_peers: bool = False
    verify_grace_seconds: int = 15


@dataclass
class PeersConfig:
    """Decentralized peer connections via libp2p sidecar.

    Separate from GatewayConfig because it's a different transport:
    the gateway listens for inbound channel adapters (CLI, Telegram,
    etc.); the peers layer is for agent-to-agent talk across the
    internet without Tailscale or a central directory.

    Disabled by default. The sidecar binary is opt-in — enabling this
    flag triggers `setup.sh` (or `agent_p2p_status` first call) to
    build `bridge/p2p/elophanto-p2pd` if missing.

    Architecture: see [docs/68-DECENTRALIZED-PEERS-RFC.md].
    """

    # Master switch. False -> sidecar never spawned, agent_discover
    # falls back to Tailscale-only.
    enabled: bool = False

    # Multiaddrs the sidecar listens on. Empty = default
    # (TCP + QUIC on random ports, all interfaces). For a publicly
    # reachable host with port forwarding, pin a fixed port:
    #   - "/ip4/0.0.0.0/tcp/4001"
    #   - "/ip4/0.0.0.0/udp/4001/quic-v1"
    listen_addrs: list[str] = field(default_factory=list)

    # Bootstrap nodes to seed the DHT. Required for cold-start peer
    # discovery — without at least one reachable bootstrap, the local
    # host can still be dialled by explicit multiaddr but won't find
    # peers by PeerID. Plural and swappable on purpose; users who don't
    # trust the default list (when one exists) point at their own.
    #
    # Format: full p2p multiaddrs, e.g.
    #   "/dnsaddr/bootstrap-1.elophanto.community/p2p/12D3KooW..."
    bootstrap_nodes: list[str] = field(default_factory=list)

    # Static circuit-relay-v2 nodes. Used by peers that AutoNAT decides
    # are not publicly reachable, as a fallback when DCUtR can't punch
    # through (~20% of home NATs are this hostile). Empty + AutoRelay
    # on means the sidecar discovers relays via DHT instead.
    relay_nodes: list[str] = field(default_factory=list)

    # Let libp2p discover relay nodes via the DHT when none are pinned.
    # Default on — without it, peers behind symmetric NAT have no path
    # to be reached at all.
    enable_auto_relay: bool = True

    # Override path to the sidecar binary. Empty = autodiscover via
    # ELOPHANTO_P2PD env var, then bridge/p2p/elophanto-p2pd, then
    # $PATH lookup. Set explicitly when packaging the agent for
    # distribution.
    sidecar_binary: str = ""


@dataclass
class HubConfig:
    """EloPhantoHub skill registry configuration."""

    enabled: bool = True
    index_url: str = (
        "https://raw.githubusercontent.com/elophanto/elophantohub/main/index.json"
    )
    auto_suggest: bool = True
    cache_ttl_hours: int = 6


@dataclass
class DiscordConfig:
    """Discord bot configuration."""

    enabled: bool = False
    bot_token_ref: str = "discord_bot_token"
    allowed_guilds: list[str] = field(default_factory=list)


@dataclass
class SlackConfig:
    """Slack app configuration."""

    enabled: bool = False
    bot_token_ref: str = "slack_bot_token"
    app_token_ref: str = "slack_app_token"
    allowed_channels: list[str] = field(default_factory=list)


@dataclass
class TelegramNotificationConfig:
    """Which events trigger Telegram notifications."""

    task_complete: bool = True
    approval_needed: bool = True
    scheduled_results: bool = True
    errors: bool = True
    daily_summary: bool = False
    daily_summary_time: str = "20:00"


@dataclass
class TelegramConfig:
    """Telegram bot configuration."""

    enabled: bool = False
    bot_token_ref: str = "telegram_bot_token"
    allowed_users: list[int] = field(default_factory=list)
    mode: str = "polling"
    max_message_length: int = 4000
    send_files: bool = True
    send_screenshots: bool = True
    notifications: TelegramNotificationConfig = field(
        default_factory=TelegramNotificationConfig
    )


@dataclass
class StorageConfig:
    """Data directory and retention configuration."""

    data_dir: str = "data"
    download_retention_hours: int = 24
    upload_retention_hours: int = 72
    cache_max_mb: int = 500
    max_file_size_mb: int = 100
    workspace_quota_mb: int = 2000
    alert_threshold_pct: float = 80.0


@dataclass
class DocumentConfig:
    """Document & media analysis configuration."""

    enabled: bool = True
    context_threshold_tokens: int = 8000
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 100
    retrieval_top_k: int = 10
    embedding_model: str = ""  # empty = use knowledge config default
    vision_model: str = ""  # empty = use LLM router
    ocr_enabled: bool = True
    ocr_languages: list[str] = field(default_factory=lambda: ["en"])
    max_collection_files: int = 50


@dataclass
class GoalsConfig:
    """Autonomous goal loop configuration."""

    enabled: bool = True
    max_checkpoints: int = 20
    max_checkpoint_attempts: int = 3
    max_goal_attempts: int = 3
    max_llm_calls_per_goal: int = 200
    max_time_per_checkpoint_seconds: int = 600
    context_summary_max_tokens: int = 1500
    auto_continue: bool = True
    # Background execution safety limits
    max_total_time_per_goal_seconds: int = 7200  # 2 hours
    cost_budget_per_goal_usd: float = 5.0
    pause_between_checkpoints_seconds: int = 2


@dataclass
class AutonomousMindConfig:
    """Autonomous background mind configuration."""

    enabled: bool = False
    wakeup_seconds: int = 300  # Default wakeup interval (5 min)
    min_wakeup_seconds: int = 300  # Defaults to wakeup_seconds at parse time
    max_wakeup_seconds: int = 3600
    budget_pct: float = 15.0  # % of daily LLM budget for autonomous ops
    max_rounds_per_wakeup: int = 8  # Max tool call rounds per cycle
    verbosity: str = "normal"  # minimal | normal | verbose


@dataclass
class HeartbeatConfig:
    """Periodic HEARTBEAT.md file-based standing orders."""

    enabled: bool = False
    file_path: str = "HEARTBEAT.md"  # relative to project root
    check_interval_seconds: int = 1800  # 30 min default
    max_rounds: int = 8  # max tool call rounds per heartbeat task
    suppress_idle: bool = True  # don't broadcast when nothing to do


@dataclass
class WebhookConfig:
    """HTTP webhook endpoints on the gateway for external triggers."""

    enabled: bool = False
    auth_token_ref: str = ""  # vault key for webhook auth (separate from gateway auth)
    max_payload_bytes: int = 65536  # 64 KB


@dataclass
class IdentityConfig:
    """Evolving agent identity configuration."""

    enabled: bool = True
    auto_evolve: bool = True
    reflection_frequency: int = 10  # tasks between deep reflections
    light_reflection_frequency: int = (
        5  # tasks between light reflections (0 = every task)
    )
    first_awakening: bool = True
    nature_file: str = "knowledge/self/nature.md"
    ego_file: str = "knowledge/self/ego.md"


@dataclass
class LearnerConfig:
    """Lesson extraction and knowledge compression configuration."""

    enabled: bool = True
    # knowledge_write compress=True uses LLM — set False to skip compression entirely
    compress_enabled: bool = True


@dataclass
class SmtpServerConfig:
    """SMTP outgoing mail server configuration."""

    host: str = ""
    port: int = 587
    use_tls: bool = True
    username_ref: str = "smtp_username"
    password_ref: str = "smtp_password"
    from_address: str = ""
    from_name: str = "EloPhanto Agent"


@dataclass
class ImapServerConfig:
    """IMAP incoming mail server configuration."""

    host: str = ""
    port: int = 993
    use_tls: bool = True
    username_ref: str = "imap_username"
    password_ref: str = "imap_password"
    mailbox: str = "INBOX"


@dataclass
class RecoveryConfig:
    """Recovery mode configuration."""

    enabled: bool = True
    auto_enter_on_provider_failure: bool = True
    auto_enter_timeout_minutes: int = 5
    auto_exit_on_recovery: bool = True
    health_check_interval_seconds: int = 60
    inactivity_timeout_minutes: int = 30


@dataclass
class EmailMonitorConfig:
    """Defaults for background inbox monitoring (started via tool, not config)."""

    poll_interval_minutes: int = 5
    persist_seen_ids: bool = True


@dataclass
class EmailConfig:
    """Agent email configuration — AgentMail or SMTP/IMAP."""

    enabled: bool = False
    provider: str = "agentmail"  # "agentmail" or "smtp"
    # AgentMail settings
    api_key_ref: str = "agentmail_api_key"
    domain: str = "agentmail.to"
    auto_create_inbox: bool = False
    inbox_display_name: str = "EloPhanto Agent"
    # SMTP/IMAP settings (used when provider: smtp)
    smtp: SmtpServerConfig = field(default_factory=SmtpServerConfig)
    imap: ImapServerConfig = field(default_factory=ImapServerConfig)
    # Background monitor defaults
    monitor: EmailMonitorConfig = field(default_factory=EmailMonitorConfig)


@dataclass
class PaymentWalletConfig:
    """Agent wallet management settings."""

    auto_create: bool = True
    low_balance_alert: float = 10.0
    default_token: str = "USDC"


@dataclass
class PaymentLimitsConfig:
    """Spending limits for payments."""

    per_transaction: float = 100.0
    daily: float = 500.0
    monthly: float = 5000.0
    per_merchant_daily: float = 200.0


@dataclass
class PaymentApprovalConfig:
    """Payment approval thresholds."""

    always_ask_above: float = 10.0
    confirm_above: float = 100.0
    cooldown_above: float = 1000.0
    cooldown_seconds: int = 300


@dataclass
class PaymentCryptoConfig:
    """Crypto payment settings — local wallet (default) or Coinbase AgentKit.

    NOTE: Coinbase AgentKit (provider: agentkit) is NOT RECOMMENDED due to
    KYA (Know Your Agent) verification requirements. Use provider: local.
    See: https://x.com/theragetech/status/2034975703033090129
    """

    enabled: bool = False
    default_chain: str = "base"  # "base", "ethereum", "solana", "solana-devnet"
    provider: str = (
        "local"  # "local" (self-custody) or "agentkit" (NOT RECOMMENDED — KYA required)
    )
    rpc_url: str = ""  # override RPC endpoint; empty = chain default
    cdp_api_key_name_ref: str = "cdp_api_key_name"
    cdp_api_key_private_ref: str = "cdp_api_key_private"
    gas_priority: str = "normal"
    max_gas_percentage: int = 10
    chains: list[str] = field(default_factory=lambda: ["base", "solana"])


@dataclass
class PaymentsConfig:
    """Agent payments configuration."""

    enabled: bool = False
    default_currency: str = "USD"
    wallet: PaymentWalletConfig = field(default_factory=PaymentWalletConfig)
    limits: PaymentLimitsConfig = field(default_factory=PaymentLimitsConfig)
    approval: PaymentApprovalConfig = field(default_factory=PaymentApprovalConfig)
    crypto: PaymentCryptoConfig = field(default_factory=PaymentCryptoConfig)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str = ""  # Populated from dict key
    transport: str = "stdio"  # "stdio" or "http" (auto-detected)
    # stdio transport
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)  # Supports "vault:key"
    cwd: str = ""
    # http transport
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)  # Supports "vault:key"
    # common
    enabled: bool = True
    permission_level: str = "moderate"
    timeout_seconds: int = 30
    startup_timeout_seconds: int = 30


@dataclass
class MCPConfig:
    """MCP client configuration."""

    enabled: bool = False
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)


@dataclass
class SelfLearningPrivacyConfig:
    """Privacy controls for self-learning data collection."""

    strip_credentials: bool = True
    strip_pii: bool = True
    strip_file_contents: bool = True
    exclude_browser_data: bool = True


@dataclass
class SelfLearningConfig:
    """Self-learning data collection configuration."""

    enabled: bool = False
    collect_endpoint: str = "https://api.elophanto.com/v1/collect"
    register_endpoint: str = "https://api.elophanto.com/v1/auth/register"
    batch_size: int = 10
    min_turns: int = 3
    success_only: bool = False
    privacy: SelfLearningPrivacyConfig = field(
        default_factory=SelfLearningPrivacyConfig
    )


@dataclass
class AgentProfileConfig:
    """Configuration for an external coding agent profile."""

    command: str = ""
    args: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    done_criteria: str = "pr_created"
    max_time_seconds: int = 3600


@dataclass
class SwarmConfig:
    """Agent swarm orchestration configuration."""

    enabled: bool = False
    max_concurrent_agents: int = 3
    monitor_interval_seconds: int = 30
    worktree_base_dir: str = ""
    cleanup_merged_worktrees: bool = True
    tmux_session_prefix: str = "elo-swarm"
    default_done_criteria: str = "pr_created"
    prompt_enrichment: bool = True
    max_enrichment_chunks: int = 5
    spawn_cooldown_seconds: int = 60
    workspace_isolation: bool = True
    output_validation: bool = True
    auto_block_suspicious: bool = True
    max_diff_lines: int = 5000
    profiles: dict[str, AgentProfileConfig] = field(default_factory=dict)


@dataclass
class KidConfig:
    """Kid agents — sandboxed child EloPhanto instances inside containers.

    Distinct from OrganizationConfig (persistent specialists with own
    gateway) and SwarmConfig (external coding agents in tmux). Kids are
    ephemeral, isolated, and connect back to the parent's gateway as
    clients. Ideal for running dangerous shell commands without host risk.
    """

    enabled: bool = True
    runtime_preference: list[str] = field(
        default_factory=lambda: ["docker", "podman", "colima"]
    )
    default_image: str = "elophanto-kid:latest"
    default_memory_mb: int = 1024
    default_cpus: float = 1.0
    default_pids_limit: int = 200
    max_concurrent_kids: int = 5
    spawn_cooldown_seconds: int = 5
    monitor_interval_seconds: int = 30
    default_network: str = "outbound-only"  # outbound-only | none | host
    outbound_allowlist: list[str] = field(
        default_factory=lambda: [
            "openrouter.ai",
            "api.openai.com",
            "github.com",
            "registry.npmjs.org",
            "pypi.org",
        ]
    )
    default_vault_scope: list[str] = field(default_factory=list)
    volume_prefix: str = "elophanto-kid-"
    max_file_read_bytes: int = 100 * 1024 * 1024  # 100 MB cap per docker cp read

    # HARDENED defaults — these MUST stay True. Disabling them weakens
    # isolation and the kid plan's safety guarantees.
    drop_capabilities: bool = True  # --cap-drop=ALL
    read_only_rootfs: bool = True  # --read-only
    no_new_privileges: bool = True  # --security-opt=no-new-privileges
    run_as_uid: int = 10001  # non-root user inside the container


@dataclass
class ChildSpecConfig:
    """Blueprint for a specialist child agent."""

    role: str = ""
    purpose: str = ""
    seed_knowledge: list[str] = field(default_factory=list)
    tools_whitelist: list[str] | None = None
    budget_pct: float = 10.0
    autonomous: bool = True
    wakeup_seconds: int = 300
    # Allowlist of vault keys this specialist may receive at boot. Empty by
    # default → no secrets passed through. Strictly stronger than the prior
    # env-name heuristic (which let anything not literally containing
    # VAULT/SECRET/PRIVATE_KEY/CREDENTIAL leak through).
    vault_scope: list[str] = field(default_factory=list)


@dataclass
class ParentChannelConfig:
    """Config for a child agent's connection back to its master."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 18789
    auth_token_ref: str = ""
    child_id: str = ""


@dataclass
class OrganizationConfig:
    """Agent organization — persistent specialist child agents."""

    enabled: bool = False
    max_children: int = 5
    port_range_start: int = 18801
    children_dir: str = ""  # Default: ~/.elophanto-children/
    monitor_interval_seconds: int = 30
    auto_approve_threshold: int = 10
    specs: dict[str, ChildSpecConfig] = field(default_factory=dict)


@dataclass
class DeploymentConfig:
    """Web deployment — deploy websites and create databases."""

    enabled: bool = False
    default_provider: str = "auto"  # auto, vercel, railway
    vercel_token_ref: str = "vercel_token"
    railway_token_ref: str = "railway_token"
    supabase_token_ref: str = "supabase_access_token"
    supabase_org_id: str = ""


@dataclass
class CommuneConfig:
    """Agent Commune — social platform for AI agents."""

    enabled: bool = False
    api_key_ref: str = "commune_api_key"
    heartbeat_interval_hours: int = 4


@dataclass
class AuthorityTierConfig:
    """Configuration for a single authority tier."""

    user_ids: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=lambda: ["chat"])


@dataclass
class AuthorityConfig:
    """Authority tier configuration for multi-user access control.

    See docs/27-SECURITY-HARDENING.md (Gap 1).
    """

    owner: AuthorityTierConfig = field(default_factory=AuthorityTierConfig)
    trusted: AuthorityTierConfig = field(default_factory=AuthorityTierConfig)
    public: AuthorityTierConfig = field(default_factory=AuthorityTierConfig)


@dataclass
class Config:
    """Top-level EloPhanto configuration."""

    agent_name: str = "EloPhanto"
    permission_mode: str = "ask_always"
    max_steps: int = 0
    max_time_seconds: int = 0
    llm: LLMConfig = field(default_factory=LLMConfig)
    shell: ShellConfig = field(default_factory=ShellConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    self_dev: SelfDevConfig = field(default_factory=SelfDevConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    peers: PeersConfig = field(default_factory=PeersConfig)
    hub: HubConfig = field(default_factory=HubConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    documents: DocumentConfig = field(default_factory=DocumentConfig)
    goals: GoalsConfig = field(default_factory=GoalsConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    learner: LearnerConfig = field(default_factory=LearnerConfig)
    payments: PaymentsConfig = field(default_factory=PaymentsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    self_learning: SelfLearningConfig = field(default_factory=SelfLearningConfig)
    swarm: SwarmConfig = field(default_factory=lambda: SwarmConfig())
    autonomous_mind: AutonomousMindConfig = field(default_factory=AutonomousMindConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    webhooks: WebhookConfig = field(default_factory=WebhookConfig)
    organization: OrganizationConfig = field(default_factory=OrganizationConfig)
    kids: KidConfig = field(default_factory=KidConfig)
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)
    commune: CommuneConfig = field(default_factory=CommuneConfig)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    parent_channel: ParentChannelConfig = field(default_factory=ParentChannelConfig)
    authority: AuthorityConfig | None = None
    workspace: str = ""
    profile: str = ""  # Distribution profile name (e.g., "developer", "marketer")
    project_root: Path = field(default_factory=Path.cwd)


def is_placeholder_key(value: str) -> bool:
    """Detect ``YOUR_*`` / ``<TODO>`` / ``CHANGEME`` style placeholder keys.

    A user who copied ``config.demo.yaml`` and didn't run the wizard
    will have placeholder strings in the api_key fields. We detect
    those and refuse to enable the provider, which prevents cryptic
    401/403 errors at first LLM call and instead points at the
    config that needs editing.
    """
    if not value:
        return False
    upper = value.upper().strip()
    if upper.startswith("YOUR_") or upper.startswith("YOUR-"):
        return True
    if upper in {"CHANGEME", "TODO", "TBD", "<TODO>", "<CHANGEME>", "PLACEHOLDER"}:
        return True
    if upper.startswith("<") and upper.endswith(">"):
        return True
    return False


def _parse_provider(name: str, data: dict[str, Any]) -> ProviderConfig:
    """Parse a provider config section.

    If the user has a placeholder ``YOUR_*`` value still in api_key
    and ``enabled: true``, force ``enabled: false`` so the router
    doesn't try to call a real provider with a bogus credential.
    The doctor command surfaces the misconfigured providers separately.
    """
    enabled = bool(data.get("enabled", False))
    api_key = data.get("api_key", "")
    # Codex / Ollama don't use api_key — skip placeholder check for those.
    if enabled and api_key and is_placeholder_key(api_key):
        logger.warning(
            "[config] Provider %r has placeholder api_key %r — "
            "auto-disabling. Run `elophanto init` or set a real "
            "key in config.yaml.",
            name,
            api_key,
        )
        enabled = False
    return ProviderConfig(
        api_key=api_key,
        enabled=enabled,
        base_url=data.get("base_url", ""),
        coding_plan=data.get("coding_plan", False),
        base_url_coding=data.get("base_url_coding", ""),
        base_url_paygo=data.get("base_url_paygo", ""),
        default_model=data.get("default_model", ""),
        max_tools=int(data.get("max_tools", 0)),
        tool_deny=data.get("tool_deny", []),
    )


def _parse_routing(data: dict[str, Any]) -> RoutingConfig:
    """Parse a routing config section.

    Supports both new ``models`` map format and legacy flat fields.
    Legacy configs (preferred_model / fallback_model / local_fallback)
    are auto-migrated into the ``models`` dict on load.
    """
    models: dict[str, str] = dict(data.get("models") or {})

    # Migrate legacy flat fields into models map
    if not models:
        prov = data.get("preferred_provider", "")
        if prov and data.get("preferred_model"):
            models[prov] = data["preferred_model"]
        fb_prov = data.get("fallback_provider", "")
        if fb_prov and data.get("fallback_model"):
            models[fb_prov] = data["fallback_model"]
        if data.get("local_fallback"):
            models["ollama"] = data["local_fallback"]

    return RoutingConfig(
        preferred_provider=data.get("preferred_provider", ""),
        models=models,
        tool_profile=data.get("tool_profile", ""),
        local_only=data.get("local_only", False),
        reasoning_effort=data.get("reasoning_effort", ""),
        # Legacy fields kept for backward compat
        preferred_model=data.get("preferred_model", ""),
        fallback_provider=data.get("fallback_provider", ""),
        fallback_model=data.get("fallback_model", ""),
        local_fallback=data.get("local_fallback", ""),
    )


def _apply_env_overrides(config: Config) -> None:
    """Apply environment variable overrides for API keys.

    Creates provider entries if they don't exist yet (important for cloud
    deployments where no config.yaml is present on the volume).
    """
    _PROVIDER_DEFAULTS: dict[str, dict] = {
        "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
        "openai": {"base_url": ""},
        "zai": {"base_url": "https://api.z.ai/api/paas/v4"},
        "kimi": {"base_url": "https://api.kilo.ai/api/gateway"},
        "huggingface": {"base_url": "https://router.huggingface.co/v1"},
        "codex": {"base_url": "https://chatgpt.com/backend-api/codex"},
    }
    _ENV_MAP = {
        "OPENROUTER_API_KEY": "openrouter",
        "OPENAI_API_KEY": "openai",
        "ZAI_API_KEY": "zai",
        "KIMI_API_KEY": "kimi",
        "HF_TOKEN": "huggingface",
    }
    for env_var, provider_name in _ENV_MAP.items():
        env_key = os.environ.get(env_var)
        if not env_key:
            continue
        if provider_name not in config.llm.providers:
            defaults = _PROVIDER_DEFAULTS.get(provider_name, {})
            config.llm.providers[provider_name] = ProviderConfig(
                api_key=env_key,
                enabled=True,
                base_url=defaults.get("base_url", ""),
            )
            if provider_name not in config.llm.provider_priority:
                config.llm.provider_priority.insert(0, provider_name)
        else:
            config.llm.providers[provider_name].api_key = env_key
            config.llm.providers[provider_name].enabled = True

    # Codex auto-detection: if ~/.codex/auth.json exists with auth_mode=chatgpt,
    # auto-enable the Codex provider. No api_key needed — OAuth tokens come
    # from the Codex CLI's login file.
    _codex_home = os.environ.get("CODEX_HOME")
    _codex_auth_path = (
        Path(_codex_home) / "auth.json"
        if _codex_home
        else Path.home() / ".codex" / "auth.json"
    )
    if _codex_auth_path.exists():
        try:
            import json as _json

            _auth_data = _json.loads(_codex_auth_path.read_text("utf-8"))
            if _auth_data.get("auth_mode") == "chatgpt":
                if "codex" not in config.llm.providers:
                    config.llm.providers["codex"] = ProviderConfig(
                        enabled=True,
                        base_url=_PROVIDER_DEFAULTS["codex"]["base_url"],
                        default_model="gpt-5.4",
                    )
                else:
                    config.llm.providers["codex"].enabled = True
        except Exception:
            pass

    # In cloud mode: override browser to headless playwright Chromium (no system Chrome)
    if os.environ.get("ELOPHANTO_CLOUD") == "1":
        config.browser.mode = "fresh"
        config.browser.headless = True
        config.browser.use_system_chrome = False
        config.browser.user_data_dir = "/tmp/elophanto-browser-profile"


def _load_profile(profile_name: str, project_root: Path) -> dict[str, Any]:
    """Load a distribution profile YAML and return its raw dict.

    Searches ``profiles/<name>.yaml`` relative to *project_root*.
    Returns an empty dict when the profile is not found or empty.
    """
    if not profile_name:
        return {}
    profile_path = project_root / "profiles" / f"{profile_name}.yaml"
    if not profile_path.exists():
        return {}
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}


def _apply_profile_overrides(raw: dict[str, Any], profile: dict[str, Any]) -> None:
    """Merge profile ``config_overrides`` into the raw config dict in-place.

    Only performs a shallow merge per top-level section so that profile
    overrides supplement (not replace) the user's base config.
    """
    overrides = profile.get("config_overrides")
    if not overrides or not isinstance(overrides, dict):
        return
    for section, values in overrides.items():
        if not isinstance(values, dict):
            continue
        if section not in raw:
            raw[section] = {}
        if isinstance(raw[section], dict):
            raw[section].update(values)


def load_config(config_path: Path | str | None = None, profile: str = "") -> Config:
    """Load and validate configuration from YAML file.

    Args:
        config_path: Path to config.yaml. If None, checks ELOPHANTO_CONFIG
                     env var, then falls back to ./config.yaml.
        profile: Distribution profile name (e.g. "developer"). When set,
                 loads ``profiles/<name>.yaml`` and merges its
                 ``config_overrides`` into the raw config before parsing.

    Returns:
        Populated Config dataclass.
    """
    if config_path is None:
        env_path = os.environ.get("ELOPHANTO_CONFIG")
        if env_path:
            config_path = Path(env_path)
        else:
            config_path = Path.cwd() / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return Config(project_root=config_path.parent)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # Resolve distribution profile: CLI flag > config file value
    profile_name = profile or raw.get("profile", "")
    if profile_name:
        profile_data = _load_profile(profile_name, config_path.parent)
        _apply_profile_overrides(raw, profile_data)

    # Parse agent section
    agent = raw.get("agent", {})
    agent_name = agent.get("name", "EloPhanto")
    permission_mode = agent.get("permission_mode", "ask_always")
    max_steps = agent.get("max_steps", 0)
    max_time_seconds = agent.get("max_time_seconds", 0)
    workspace = agent.get("workspace", "")

    # Parse LLM section
    llm_raw = raw.get("llm", {})

    providers: dict[str, ProviderConfig] = {}
    for name, pdata in llm_raw.get("providers", {}).items():
        providers[name] = _parse_provider(name, pdata or {})

    provider_priority = llm_raw.get("provider_priority", [])

    routing: dict[str, RoutingConfig] = {}
    for task_type, rdata in llm_raw.get("routing", {}).items():
        routing[task_type] = _parse_routing(rdata or {})

    budget_raw = llm_raw.get("budget", {})
    budget = BudgetConfig(
        daily_limit_usd=budget_raw.get("daily_limit_usd", 10.0),
        per_task_limit_usd=budget_raw.get("per_task_limit_usd", 2.0),
    )

    # Parse custom tool profiles (if any)
    tool_profiles_raw = llm_raw.get("tool_profiles", {})
    tool_profiles: dict[str, list[str]] = {}
    for profile_name, groups in tool_profiles_raw.items():
        if isinstance(groups, dict):
            tool_profiles[profile_name] = groups.get("groups", [])
        elif isinstance(groups, list):
            tool_profiles[profile_name] = groups

    llm_config = LLMConfig(
        providers=providers,
        provider_priority=provider_priority,
        routing=routing,
        budget=budget,
        tool_profiles=tool_profiles,
        vision_model=llm_raw.get("vision_model", ""),
    )

    # Parse shell section
    shell_raw = raw.get("shell", {})
    shell_config = ShellConfig(
        timeout=shell_raw.get("timeout", 30),
        blacklist_patterns=shell_raw.get("blacklist_patterns", []),
        safe_commands=shell_raw.get("safe_commands", []),
        max_concurrent_processes=shell_raw.get("max_concurrent_processes", 10),
    )

    # Parse knowledge section
    knowledge_raw = raw.get("knowledge", {})
    knowledge_config = KnowledgeConfig(
        knowledge_dir=knowledge_raw.get("knowledge_dir", "knowledge"),
        embedding_provider=knowledge_raw.get("embedding_provider", "auto"),
        embedding_model=knowledge_raw.get("embedding_model", "nomic-embed-text"),
        embedding_fallback=knowledge_raw.get("embedding_fallback", "mxbai-embed-large"),
        embedding_openrouter_model=knowledge_raw.get(
            "embedding_openrouter_model", "google/gemini-embedding-001"
        ),
        embedding_dimensions=knowledge_raw.get("embedding_dimensions", 768),
        chunk_max_tokens=knowledge_raw.get("chunk_max_tokens", 1000),
        chunk_min_tokens=knowledge_raw.get("chunk_min_tokens", 50),
        search_top_k=knowledge_raw.get("search_top_k", 5),
        auto_index_on_startup=knowledge_raw.get("auto_index_on_startup", True),
    )

    # Parse database section
    db_raw = raw.get("database", {})
    database_config = DatabaseConfig(
        db_path=db_raw.get("db_path", "data/elophanto.db"),
    )

    # Parse plugins section
    plugins_raw = raw.get("plugins", {})
    plugins_config = PluginConfig(
        plugins_dir=plugins_raw.get("plugins_dir", "plugins"),
        auto_load=plugins_raw.get("auto_load", True),
    )

    # Parse self-dev section
    self_dev_raw = raw.get("self_dev", {})
    self_dev_config = SelfDevConfig(
        max_llm_calls=self_dev_raw.get("max_llm_calls", 50),
        max_time_seconds=self_dev_raw.get("max_time_seconds", 1800),
        max_retries=self_dev_raw.get("max_retries", 3),
        test_timeout=self_dev_raw.get("test_timeout", 60),
        review_model_override=self_dev_raw.get("review_model_override", ""),
    )

    # Parse browser section
    browser_raw = raw.get("browser", {})
    browser_config = BrowserConfig(
        enabled=browser_raw.get("enabled", False),
        mode=browser_raw.get("mode", "fresh"),
        headless=browser_raw.get("headless", False),
        cdp_port=browser_raw.get("cdp_port", 9222),
        cdp_ws_endpoint=browser_raw.get("cdp_ws_endpoint", ""),
        user_data_dir=browser_raw.get("user_data_dir", ""),
        profile_directory=browser_raw.get("profile_directory", "Default"),
        use_system_chrome=browser_raw.get("use_system_chrome", True),
        viewport_width=browser_raw.get("viewport_width", 1280),
        viewport_height=browser_raw.get("viewport_height", 720),
        vision_model=browser_raw.get("vision_model", "google/gemini-2.0-flash-001"),
    )

    # Parse desktop section
    desktop_raw = raw.get("desktop", {})
    desktop_config = DesktopConfig(
        enabled=desktop_raw.get("enabled", False),
        mode=desktop_raw.get("mode", "local"),
        vm_ip=desktop_raw.get("vm_ip", ""),
        server_port=desktop_raw.get("server_port", 5000),
        screen_width=desktop_raw.get("screen_width", 1920),
        screen_height=desktop_raw.get("screen_height", 1080),
        observation_type=desktop_raw.get("observation_type", "screenshot"),
        max_steps=desktop_raw.get("max_steps", 15),
        sleep_after_action=desktop_raw.get("sleep_after_action", 1.0),
    )

    # Parse scheduler section
    scheduler_raw = raw.get("scheduler", {})
    scheduler_config = SchedulerConfig(
        enabled=scheduler_raw.get("enabled", False),
        max_concurrent_tasks=scheduler_raw.get("max_concurrent_tasks", 1),
        default_max_retries=scheduler_raw.get("default_max_retries", 3),
        task_timeout_seconds=scheduler_raw.get("task_timeout_seconds", 600),
    )

    # Parse telegram section
    tg_raw = raw.get("telegram", {})
    tg_notif_raw = tg_raw.get("notifications", {})
    telegram_config = TelegramConfig(
        enabled=tg_raw.get("enabled", False),
        bot_token_ref=tg_raw.get("bot_token_ref", "telegram_bot_token"),
        allowed_users=tg_raw.get("allowed_users", []),
        mode=tg_raw.get("mode", "polling"),
        max_message_length=tg_raw.get("max_message_length", 4000),
        send_files=tg_raw.get("send_files", True),
        send_screenshots=tg_raw.get("send_screenshots", True),
        notifications=TelegramNotificationConfig(
            task_complete=tg_notif_raw.get("task_complete", True),
            approval_needed=tg_notif_raw.get("approval_needed", True),
            scheduled_results=tg_notif_raw.get("scheduled_results", True),
            errors=tg_notif_raw.get("errors", True),
            daily_summary=tg_notif_raw.get("daily_summary", False),
            daily_summary_time=tg_notif_raw.get("daily_summary_time", "20:00"),
        ),
    )

    # Parse gateway section
    gw_raw = raw.get("gateway", {})
    gateway_config = GatewayConfig(
        enabled=gw_raw.get("enabled", True),
        host=gw_raw.get("host", "127.0.0.1"),
        port=gw_raw.get("port", 18789),
        auth_token_ref=gw_raw.get("auth_token_ref", ""),
        max_sessions=gw_raw.get("max_sessions", 50),
        session_timeout_hours=gw_raw.get("session_timeout_hours", 24),
        unified_sessions=gw_raw.get("unified_sessions", True),
        tls_cert=gw_raw.get("tls_cert", ""),
        tls_key=gw_raw.get("tls_key", ""),
        require_verified_peers=gw_raw.get("require_verified_peers", False),
        verify_grace_seconds=gw_raw.get("verify_grace_seconds", 15),
    )

    # Parse peers section (libp2p sidecar; optional, off by default)
    peers_raw = raw.get("peers", {})
    peers_config = PeersConfig(
        enabled=peers_raw.get("enabled", False),
        listen_addrs=list(peers_raw.get("listen_addrs") or []),
        bootstrap_nodes=list(peers_raw.get("bootstrap_nodes") or []),
        relay_nodes=list(peers_raw.get("relay_nodes") or []),
        enable_auto_relay=peers_raw.get("enable_auto_relay", True),
        sidecar_binary=peers_raw.get("sidecar_binary", ""),
    )

    # Parse hub section
    hub_raw = raw.get("hub", {})
    hub_config = HubConfig(
        enabled=hub_raw.get("enabled", True),
        index_url=hub_raw.get(
            "index_url",
            "https://raw.githubusercontent.com/elophanto/elophantohub/main/index.json",
        ),
        auto_suggest=hub_raw.get("auto_suggest", True),
        cache_ttl_hours=hub_raw.get("cache_ttl_hours", 6),
    )

    # Parse discord section
    discord_raw = raw.get("discord", {})
    discord_config = DiscordConfig(
        enabled=discord_raw.get("enabled", False),
        bot_token_ref=discord_raw.get("bot_token_ref", "discord_bot_token"),
        allowed_guilds=discord_raw.get("allowed_guilds", []),
    )

    # Parse slack section
    slack_raw = raw.get("slack", {})
    slack_config = SlackConfig(
        enabled=slack_raw.get("enabled", False),
        bot_token_ref=slack_raw.get("bot_token_ref", "slack_bot_token"),
        app_token_ref=slack_raw.get("app_token_ref", "slack_app_token"),
        allowed_channels=slack_raw.get("allowed_channels", []),
    )

    # Parse storage section
    storage_raw = raw.get("storage", {})
    storage_config = StorageConfig(
        data_dir=storage_raw.get("data_dir", "data"),
        download_retention_hours=storage_raw.get("download_retention_hours", 24),
        upload_retention_hours=storage_raw.get("upload_retention_hours", 72),
        cache_max_mb=storage_raw.get("cache_max_mb", 500),
        max_file_size_mb=storage_raw.get("max_file_size_mb", 100),
        workspace_quota_mb=storage_raw.get("workspace_quota_mb", 2000),
        alert_threshold_pct=storage_raw.get("alert_threshold_pct", 80.0),
    )

    # Parse documents section
    docs_raw = raw.get("documents", {})
    documents_config = DocumentConfig(
        enabled=docs_raw.get("enabled", True),
        context_threshold_tokens=docs_raw.get("context_threshold_tokens", 8000),
        chunk_size_tokens=docs_raw.get("chunk_size_tokens", 512),
        chunk_overlap_tokens=docs_raw.get("chunk_overlap_tokens", 100),
        retrieval_top_k=docs_raw.get("retrieval_top_k", 10),
        embedding_model=docs_raw.get("embedding_model", ""),
        vision_model=docs_raw.get("vision_model", ""),
        ocr_enabled=docs_raw.get("ocr_enabled", True),
        ocr_languages=docs_raw.get("ocr_languages", ["en"]),
        max_collection_files=docs_raw.get("max_collection_files", 50),
    )

    # Parse goals section
    goals_raw = raw.get("goals", {})
    goals_config = GoalsConfig(
        enabled=goals_raw.get("enabled", True),
        max_checkpoints=goals_raw.get("max_checkpoints", 20),
        max_checkpoint_attempts=goals_raw.get("max_checkpoint_attempts", 3),
        max_goal_attempts=goals_raw.get("max_goal_attempts", 3),
        max_llm_calls_per_goal=goals_raw.get("max_llm_calls_per_goal", 200),
        max_time_per_checkpoint_seconds=goals_raw.get(
            "max_time_per_checkpoint_seconds", 600
        ),
        context_summary_max_tokens=goals_raw.get("context_summary_max_tokens", 1500),
        auto_continue=goals_raw.get("auto_continue", True),
        max_total_time_per_goal_seconds=goals_raw.get(
            "max_total_time_per_goal_seconds", 7200
        ),
        cost_budget_per_goal_usd=goals_raw.get("cost_budget_per_goal_usd", 5.0),
        pause_between_checkpoints_seconds=goals_raw.get(
            "pause_between_checkpoints_seconds", 2
        ),
    )

    # Parse identity section
    identity_raw = raw.get("identity", {})
    identity_config = IdentityConfig(
        enabled=identity_raw.get("enabled", True),
        auto_evolve=identity_raw.get("auto_evolve", True),
        reflection_frequency=identity_raw.get("reflection_frequency", 10),
        light_reflection_frequency=identity_raw.get("light_reflection_frequency", 5),
        first_awakening=identity_raw.get("first_awakening", True),
        nature_file=identity_raw.get("nature_file", "knowledge/self/nature.md"),
        ego_file=identity_raw.get("ego_file", "knowledge/self/ego.md"),
    )

    # Parse learner section
    learner_raw = raw.get("learner", {})
    learner_config = LearnerConfig(
        enabled=learner_raw.get("enabled", True),
        compress_enabled=learner_raw.get("compress_enabled", True),
    )

    # Parse payments section
    pay_raw = raw.get("payments", {})
    pay_wallet_raw = pay_raw.get("wallet", {})
    pay_limits_raw = pay_raw.get("limits", {})
    pay_approval_raw = pay_raw.get("approval", {})
    pay_crypto_raw = pay_raw.get("crypto", {})
    payments_config = PaymentsConfig(
        enabled=pay_raw.get("enabled", False),
        default_currency=pay_raw.get("default_currency", "USD"),
        wallet=PaymentWalletConfig(
            auto_create=pay_wallet_raw.get("auto_create", True),
            low_balance_alert=pay_wallet_raw.get("low_balance_alert", 10.0),
            default_token=pay_wallet_raw.get("default_token", "USDC"),
        ),
        limits=PaymentLimitsConfig(
            per_transaction=pay_limits_raw.get("per_transaction", 100.0),
            daily=pay_limits_raw.get("daily", 500.0),
            monthly=pay_limits_raw.get("monthly", 5000.0),
            per_merchant_daily=pay_limits_raw.get("per_merchant_daily", 200.0),
        ),
        approval=PaymentApprovalConfig(
            always_ask_above=pay_approval_raw.get("always_ask_above", 10.0),
            confirm_above=pay_approval_raw.get("confirm_above", 100.0),
            cooldown_above=pay_approval_raw.get("cooldown_above", 1000.0),
            cooldown_seconds=pay_approval_raw.get("cooldown_seconds", 300),
        ),
        crypto=PaymentCryptoConfig(
            enabled=pay_crypto_raw.get("enabled", False),
            default_chain=pay_crypto_raw.get("default_chain", "base"),
            provider=pay_crypto_raw.get("provider", "local"),
            rpc_url=pay_crypto_raw.get("rpc_url", ""),
            cdp_api_key_name_ref=pay_crypto_raw.get(
                "cdp_api_key_name_ref", "cdp_api_key_name"
            ),
            cdp_api_key_private_ref=pay_crypto_raw.get(
                "cdp_api_key_private_ref", "cdp_api_key_private"
            ),
            gas_priority=pay_crypto_raw.get("gas_priority", "normal"),
            max_gas_percentage=pay_crypto_raw.get("max_gas_percentage", 10),
            chains=pay_crypto_raw.get("chains", ["base"]),
        ),
    )

    # Parse email section
    email_raw = raw.get("email", {})
    smtp_raw = email_raw.get("smtp", {})
    imap_raw = email_raw.get("imap", {})
    monitor_raw = email_raw.get("monitor", {})
    email_config = EmailConfig(
        enabled=email_raw.get("enabled", False),
        provider=email_raw.get("provider", "agentmail"),
        api_key_ref=email_raw.get("api_key_ref", "agentmail_api_key"),
        domain=email_raw.get("domain", "agentmail.to"),
        auto_create_inbox=email_raw.get("auto_create_inbox", False),
        inbox_display_name=email_raw.get("inbox_display_name", "EloPhanto Agent"),
        smtp=SmtpServerConfig(
            host=smtp_raw.get("host", ""),
            port=smtp_raw.get("port", 587),
            use_tls=smtp_raw.get("use_tls", True),
            username_ref=smtp_raw.get("username_ref", "smtp_username"),
            password_ref=smtp_raw.get("password_ref", "smtp_password"),
            from_address=smtp_raw.get("from_address", ""),
            from_name=smtp_raw.get("from_name", "EloPhanto Agent"),
        ),
        imap=ImapServerConfig(
            host=imap_raw.get("host", ""),
            port=imap_raw.get("port", 993),
            use_tls=imap_raw.get("use_tls", True),
            username_ref=imap_raw.get("username_ref", "imap_username"),
            password_ref=imap_raw.get("password_ref", "imap_password"),
            mailbox=imap_raw.get("mailbox", "INBOX"),
        ),
        monitor=EmailMonitorConfig(
            poll_interval_minutes=monitor_raw.get("poll_interval_minutes", 5),
            persist_seen_ids=monitor_raw.get("persist_seen_ids", True),
        ),
    )

    # Parse recovery section
    recovery_raw = raw.get("recovery", {})
    recovery_config = RecoveryConfig(
        enabled=recovery_raw.get("enabled", True),
        auto_enter_on_provider_failure=recovery_raw.get(
            "auto_enter_on_provider_failure", True
        ),
        auto_enter_timeout_minutes=recovery_raw.get("auto_enter_timeout_minutes", 5),
        auto_exit_on_recovery=recovery_raw.get("auto_exit_on_recovery", True),
        health_check_interval_seconds=recovery_raw.get(
            "health_check_interval_seconds", 60
        ),
        inactivity_timeout_minutes=recovery_raw.get("inactivity_timeout_minutes", 30),
    )

    # Parse MCP section
    mcp_raw = raw.get("mcp", {})
    mcp_servers: dict[str, MCPServerConfig] = {}
    for srv_name, srv_data in (mcp_raw.get("servers") or {}).items():
        srv_data = srv_data or {}
        transport = srv_data.get("transport", "")
        if not transport:
            transport = "http" if srv_data.get("url") else "stdio"
        mcp_servers[srv_name] = MCPServerConfig(
            name=srv_name,
            transport=transport,
            command=srv_data.get("command", ""),
            args=srv_data.get("args", []),
            env=srv_data.get("env", {}),
            cwd=srv_data.get("cwd", ""),
            url=srv_data.get("url", ""),
            headers=srv_data.get("headers", {}),
            enabled=srv_data.get("enabled", True),
            permission_level=srv_data.get("permission_level", "moderate"),
            timeout_seconds=srv_data.get("timeout_seconds", 30),
            startup_timeout_seconds=srv_data.get("startup_timeout_seconds", 30),
        )
    mcp_config = MCPConfig(
        enabled=mcp_raw.get("enabled", False),
        servers=mcp_servers,
    )

    # Parse self_learning section
    sl_raw = raw.get("self_learning", {})
    sl_privacy_raw = sl_raw.get("privacy", {})
    self_learning_config = SelfLearningConfig(
        enabled=sl_raw.get("enabled", False),
        collect_endpoint=sl_raw.get(
            "collect_endpoint", "https://api.elophanto.com/v1/collect"
        ),
        register_endpoint=sl_raw.get(
            "register_endpoint", "https://api.elophanto.com/v1/auth/register"
        ),
        batch_size=sl_raw.get("batch_size", 10),
        min_turns=sl_raw.get("min_turns", 3),
        success_only=sl_raw.get("success_only", True),
        privacy=SelfLearningPrivacyConfig(
            strip_credentials=sl_privacy_raw.get("strip_credentials", True),
            strip_pii=sl_privacy_raw.get("strip_pii", True),
            strip_file_contents=sl_privacy_raw.get("strip_file_contents", True),
            exclude_browser_data=sl_privacy_raw.get("exclude_browser_data", True),
        ),
    )

    # Parse swarm section
    swarm_raw = raw.get("swarm", {})
    swarm_profiles: dict[str, AgentProfileConfig] = {}
    for prof_name, prof_data in (swarm_raw.get("profiles") or {}).items():
        prof_data = prof_data or {}
        swarm_profiles[prof_name] = AgentProfileConfig(
            command=prof_data.get("command", ""),
            args=prof_data.get("args", []),
            strengths=prof_data.get("strengths", []),
            env=prof_data.get("env", {}),
            done_criteria=prof_data.get("done_criteria", "pr_created"),
            max_time_seconds=prof_data.get("max_time_seconds", 3600),
        )
    swarm_config = SwarmConfig(
        enabled=swarm_raw.get("enabled", False),
        max_concurrent_agents=swarm_raw.get("max_concurrent_agents", 3),
        monitor_interval_seconds=swarm_raw.get("monitor_interval_seconds", 30),
        worktree_base_dir=swarm_raw.get("worktree_base_dir", ""),
        cleanup_merged_worktrees=swarm_raw.get("cleanup_merged_worktrees", True),
        tmux_session_prefix=swarm_raw.get("tmux_session_prefix", "elo-swarm"),
        default_done_criteria=swarm_raw.get("default_done_criteria", "pr_created"),
        prompt_enrichment=swarm_raw.get("prompt_enrichment", True),
        max_enrichment_chunks=swarm_raw.get("max_enrichment_chunks", 5),
        spawn_cooldown_seconds=swarm_raw.get("spawn_cooldown_seconds", 60),
        workspace_isolation=swarm_raw.get("workspace_isolation", True),
        output_validation=swarm_raw.get("output_validation", True),
        auto_block_suspicious=swarm_raw.get("auto_block_suspicious", True),
        max_diff_lines=swarm_raw.get("max_diff_lines", 5000),
        profiles=swarm_profiles,
    )

    # Parse kids section
    kids_raw = raw.get("kids", {})
    kids_config = KidConfig(
        enabled=kids_raw.get("enabled", True),
        runtime_preference=kids_raw.get(
            "runtime_preference", ["docker", "podman", "colima"]
        ),
        default_image=kids_raw.get("default_image", "elophanto-kid:latest"),
        default_memory_mb=kids_raw.get("default_memory_mb", 1024),
        default_cpus=kids_raw.get("default_cpus", 1.0),
        default_pids_limit=kids_raw.get("default_pids_limit", 200),
        max_concurrent_kids=kids_raw.get("max_concurrent_kids", 5),
        spawn_cooldown_seconds=kids_raw.get("spawn_cooldown_seconds", 5),
        monitor_interval_seconds=kids_raw.get("monitor_interval_seconds", 30),
        default_network=kids_raw.get("default_network", "outbound-only"),
        outbound_allowlist=kids_raw.get(
            "outbound_allowlist",
            [
                "openrouter.ai",
                "api.openai.com",
                "github.com",
                "registry.npmjs.org",
                "pypi.org",
            ],
        ),
        default_vault_scope=kids_raw.get("default_vault_scope", []),
        volume_prefix=kids_raw.get("volume_prefix", "elophanto-kid-"),
        max_file_read_bytes=kids_raw.get("max_file_read_bytes", 100 * 1024 * 1024),
        # Hardening flags — DO NOT default these to False. Plan invariant.
        drop_capabilities=kids_raw.get("drop_capabilities", True),
        read_only_rootfs=kids_raw.get("read_only_rootfs", True),
        no_new_privileges=kids_raw.get("no_new_privileges", True),
        run_as_uid=kids_raw.get("run_as_uid", 10001),
    )

    # Parse autonomous_mind section
    am_raw = raw.get("autonomous_mind", {})
    _wakeup_sec = am_raw.get("wakeup_seconds", 300)
    autonomous_mind_config = AutonomousMindConfig(
        enabled=am_raw.get("enabled", False),
        wakeup_seconds=_wakeup_sec,
        min_wakeup_seconds=am_raw.get("min_wakeup_seconds", _wakeup_sec),
        max_wakeup_seconds=am_raw.get("max_wakeup_seconds", 3600),
        budget_pct=am_raw.get("budget_pct", 15.0),
        max_rounds_per_wakeup=am_raw.get("max_rounds_per_wakeup", 8),
        verbosity=am_raw.get("verbosity", "normal"),
    )

    # Parse heartbeat section
    hb_raw = raw.get("heartbeat", {})
    heartbeat_config = HeartbeatConfig(
        enabled=hb_raw.get("enabled", False),
        file_path=hb_raw.get("file_path", "HEARTBEAT.md"),
        check_interval_seconds=hb_raw.get("check_interval_seconds", 1800),
        max_rounds=hb_raw.get("max_rounds", 8),
        suppress_idle=hb_raw.get("suppress_idle", True),
    )

    # Parse webhooks section
    wh_raw = raw.get("webhooks", {})
    webhooks_config = WebhookConfig(
        enabled=wh_raw.get("enabled", False),
        auth_token_ref=wh_raw.get("auth_token_ref", ""),
        max_payload_bytes=wh_raw.get("max_payload_bytes", 65536),
    )

    # Parse organization section
    org_raw = raw.get("organization", {})
    org_specs: dict[str, ChildSpecConfig] = {}
    for spec_name, spec_data in (org_raw.get("specs") or {}).items():
        if isinstance(spec_data, dict):
            org_specs[spec_name] = ChildSpecConfig(
                role=spec_data.get("role", spec_name),
                purpose=spec_data.get("purpose", ""),
                seed_knowledge=spec_data.get("seed_knowledge", []),
                tools_whitelist=spec_data.get("tools_whitelist"),
                budget_pct=spec_data.get("budget_pct", 10.0),
                autonomous=spec_data.get("autonomous", True),
                wakeup_seconds=spec_data.get("wakeup_seconds", 300),
                vault_scope=spec_data.get("vault_scope", []),
            )
    organization_config = OrganizationConfig(
        enabled=org_raw.get("enabled", False),
        max_children=org_raw.get("max_children", 5),
        port_range_start=org_raw.get("port_range_start", 18801),
        children_dir=org_raw.get("children_dir", ""),
        monitor_interval_seconds=org_raw.get("monitor_interval_seconds", 30),
        auto_approve_threshold=org_raw.get("auto_approve_threshold", 10),
        specs=org_specs,
    )

    # Parse deployment section
    deploy_raw = raw.get("deployment", {})
    deployment_config = DeploymentConfig(
        enabled=deploy_raw.get("enabled", False),
        default_provider=deploy_raw.get("default_provider", "auto"),
        vercel_token_ref=deploy_raw.get("vercel_token_ref", "vercel_token"),
        railway_token_ref=deploy_raw.get("railway_token_ref", "railway_token"),
        supabase_token_ref=deploy_raw.get(
            "supabase_token_ref", "supabase_access_token"
        ),
        supabase_org_id=deploy_raw.get("supabase_org_id", ""),
    )

    # Parse commune section
    commune_raw = raw.get("commune", {})
    commune_config = CommuneConfig(
        enabled=commune_raw.get("enabled", False),
        api_key_ref=commune_raw.get("api_key_ref", "commune_api_key"),
        heartbeat_interval_hours=commune_raw.get("heartbeat_interval_hours", 4),
    )

    # Parse parent channel section (child agents connecting to master)
    parent_raw = raw.get("parent", {})
    parent_channel_config = ParentChannelConfig(
        enabled=parent_raw.get("enabled", False),
        host=parent_raw.get("host", "127.0.0.1"),
        port=parent_raw.get("port", 18789),
        auth_token_ref=parent_raw.get("auth_token_ref", ""),
        child_id=parent_raw.get("child_id", ""),
    )

    # Parse authority section (optional — None means all users are owner)
    authority_raw = raw.get("authority")
    authority_config: AuthorityConfig | None = None
    if authority_raw and isinstance(authority_raw, dict):
        owner_raw = authority_raw.get("owner", {}) or {}
        trusted_raw = authority_raw.get("trusted", {}) or {}
        public_raw = authority_raw.get("public", {}) or {}
        authority_config = AuthorityConfig(
            owner=AuthorityTierConfig(
                user_ids=[str(uid) for uid in (owner_raw.get("user_ids") or [])],
                capabilities=owner_raw.get("capabilities") or ["all"],
            ),
            trusted=AuthorityTierConfig(
                user_ids=[str(uid) for uid in (trusted_raw.get("user_ids") or [])],
                capabilities=trusted_raw.get("capabilities")
                or ["chat", "read_tools", "safe_tools"],
            ),
            public=AuthorityTierConfig(
                user_ids=[str(uid) for uid in (public_raw.get("user_ids") or [])],
                capabilities=public_raw.get("capabilities") or ["chat"],
            ),
        )

    config = Config(
        agent_name=agent_name,
        permission_mode=permission_mode,
        max_steps=max_steps,
        max_time_seconds=max_time_seconds,
        workspace=workspace,
        llm=llm_config,
        shell=shell_config,
        knowledge=knowledge_config,
        database=database_config,
        plugins=plugins_config,
        self_dev=self_dev_config,
        browser=browser_config,
        scheduler=scheduler_config,
        telegram=telegram_config,
        gateway=gateway_config,
        peers=peers_config,
        hub=hub_config,
        discord=discord_config,
        slack=slack_config,
        storage=storage_config,
        documents=documents_config,
        goals=goals_config,
        identity=identity_config,
        learner=learner_config,
        payments=payments_config,
        email=email_config,
        recovery=recovery_config,
        mcp=mcp_config,
        self_learning=self_learning_config,
        swarm=swarm_config,
        autonomous_mind=autonomous_mind_config,
        heartbeat=heartbeat_config,
        webhooks=webhooks_config,
        organization=organization_config,
        kids=kids_config,
        deployment=deployment_config,
        commune=commune_config,
        desktop=desktop_config,
        parent_channel=parent_channel_config,
        authority=authority_config,
        profile=profile_name,
        project_root=config_path.parent,
    )

    _apply_env_overrides(config)
    return config
