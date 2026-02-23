"""Configuration system for EloPhanto.

Loads config.yaml, validates required fields, and provides typed access.
Supports environment variable overrides for API keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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
    fast_model: str = ""


@dataclass
class RoutingConfig:
    """Per-task-type routing preferences."""

    preferred_provider: str = ""
    models: dict[str, str] = field(default_factory=dict)  # provider -> model
    local_only: bool = False
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


@dataclass
class ShellConfig:
    """Shell execution configuration."""

    timeout: int = 30
    blacklist_patterns: list[str] = field(default_factory=list)
    safe_commands: list[str] = field(default_factory=list)


@dataclass
class KnowledgeConfig:
    """Knowledge base configuration."""

    knowledge_dir: str = "knowledge"
    embedding_provider: str = "auto"  # "auto", "openrouter", or "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_fallback: str = "mxbai-embed-large"
    embedding_openrouter_model: str = "qwen/qwen3-embedding-8b"
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
class IdentityConfig:
    """Evolving agent identity configuration."""

    enabled: bool = True
    auto_evolve: bool = True
    reflection_frequency: int = 10
    first_awakening: bool = True
    nature_file: str = "knowledge/self/nature.md"


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
    """Crypto payment settings — local wallet (default) or Coinbase AgentKit."""

    enabled: bool = False
    default_chain: str = "base"
    provider: str = "local"  # "local" (self-custody) or "agentkit" (Coinbase CDP)
    rpc_url: str = ""  # override RPC endpoint; empty = chain default
    cdp_api_key_name_ref: str = "cdp_api_key_name"
    cdp_api_key_private_ref: str = "cdp_api_key_private"
    gas_priority: str = "normal"
    max_gas_percentage: int = 10
    chains: list[str] = field(default_factory=lambda: ["base"])


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
    hub: HubConfig = field(default_factory=HubConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    documents: DocumentConfig = field(default_factory=DocumentConfig)
    goals: GoalsConfig = field(default_factory=GoalsConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    payments: PaymentsConfig = field(default_factory=PaymentsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    self_learning: SelfLearningConfig = field(default_factory=SelfLearningConfig)
    project_root: Path = field(default_factory=Path.cwd)


def _parse_provider(name: str, data: dict[str, Any]) -> ProviderConfig:
    """Parse a provider config section."""
    return ProviderConfig(
        api_key=data.get("api_key", ""),
        enabled=data.get("enabled", False),
        base_url=data.get("base_url", ""),
        coding_plan=data.get("coding_plan", False),
        base_url_coding=data.get("base_url_coding", ""),
        base_url_paygo=data.get("base_url_paygo", ""),
        default_model=data.get("default_model", ""),
        fast_model=data.get("fast_model", ""),
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
        local_only=data.get("local_only", False),
        # Legacy fields kept for backward compat
        preferred_model=data.get("preferred_model", ""),
        fallback_provider=data.get("fallback_provider", ""),
        fallback_model=data.get("fallback_model", ""),
        local_fallback=data.get("local_fallback", ""),
    )


def _apply_env_overrides(config: Config) -> None:
    """Apply environment variable overrides for API keys."""
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key and "openrouter" in config.llm.providers:
        config.llm.providers["openrouter"].api_key = env_key
        config.llm.providers["openrouter"].enabled = True

    env_key = os.environ.get("ZAI_API_KEY")
    if env_key and "zai" in config.llm.providers:
        config.llm.providers["zai"].api_key = env_key
        config.llm.providers["zai"].enabled = True


def load_config(config_path: Path | str | None = None) -> Config:
    """Load and validate configuration from YAML file.

    Args:
        config_path: Path to config.yaml. If None, checks ELOPHANTO_CONFIG
                     env var, then falls back to ./config.yaml.

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

    # Parse agent section
    agent = raw.get("agent", {})
    agent_name = agent.get("name", "EloPhanto")
    permission_mode = agent.get("permission_mode", "ask_always")
    max_steps = agent.get("max_steps", 0)
    max_time_seconds = agent.get("max_time_seconds", 0)

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

    llm_config = LLMConfig(
        providers=providers,
        provider_priority=provider_priority,
        routing=routing,
        budget=budget,
    )

    # Parse shell section
    shell_raw = raw.get("shell", {})
    shell_config = ShellConfig(
        timeout=shell_raw.get("timeout", 30),
        blacklist_patterns=shell_raw.get("blacklist_patterns", []),
        safe_commands=shell_raw.get("safe_commands", []),
    )

    # Parse knowledge section
    knowledge_raw = raw.get("knowledge", {})
    knowledge_config = KnowledgeConfig(
        knowledge_dir=knowledge_raw.get("knowledge_dir", "knowledge"),
        embedding_provider=knowledge_raw.get("embedding_provider", "auto"),
        embedding_model=knowledge_raw.get("embedding_model", "nomic-embed-text"),
        embedding_fallback=knowledge_raw.get("embedding_fallback", "mxbai-embed-large"),
        embedding_openrouter_model=knowledge_raw.get(
            "embedding_openrouter_model", "qwen/qwen3-embedding-8b"
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
        first_awakening=identity_raw.get("first_awakening", True),
        nature_file=identity_raw.get("nature_file", "knowledge/self/nature.md"),
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

    config = Config(
        agent_name=agent_name,
        permission_mode=permission_mode,
        max_steps=max_steps,
        max_time_seconds=max_time_seconds,
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
        hub=hub_config,
        discord=discord_config,
        slack=slack_config,
        storage=storage_config,
        documents=documents_config,
        goals=goals_config,
        identity=identity_config,
        payments=payments_config,
        email=email_config,
        recovery=recovery_config,
        mcp=mcp_config,
        self_learning=self_learning_config,
        project_root=config_path.parent,
    )

    _apply_env_overrides(config)
    return config
