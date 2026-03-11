---
title: EloPhanto Capabilities
created: 2026-02-17
updated: 2026-03-10
tags: tools, capabilities, features, platform-docs
scope: system
covers: [tools/**/*.py, channels/*.py, core/router.py, core/payments/*.py]
---

# Current Capabilities

> Full feature inventory. Auto-reference for visibility posts, docs, and self-awareness.
> Inspired by [Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184).

## System Tools (9 tools)

| Tool | Permission | Description |
|------|-----------|-------------|
| `shell_execute` | destructive | Run shell commands with safety blacklist and process group timeout |
| `file_read` | safe | Read file contents with optional line ranges |
| `file_write` | moderate | Create or overwrite files with .bak backup |
| `file_list` | safe | List directory contents with glob filtering |
| `file_delete` | destructive | Delete files or directories |
| `file_move` | moderate | Move or rename files and directories |
| `llm_call` | safe | Make sub-LLM calls through the router |
| `vault_lookup` | safe | Look up credentials from the encrypted vault |
| `vault_set` | critical | Store a credential in the encrypted vault |

## Browser Tools (49 tools via Node.js bridge)

Real Chrome automation using the user's actual profile and sessions. Stealth mode strips all Playwright automation flags — no `--enable-automation`, no `--no-sandbox`, zero detectable signals. Vision model proxy describes screenshots as text for non-vision planning models.

Categories: navigation, clicking, typing, screenshots, element inspection, DOM search, console/network logs, cookies, storage, tabs, drag-and-drop, scrolling, waiting, JavaScript execution, HTML paste, text selection, file operations.

Key tools: `browser_navigate`, `browser_click`, `browser_click_text`, `browser_type`, `browser_extract`, `browser_read_semantic`, `browser_screenshot`, `browser_paste_html`, `browser_select_text`, `browser_eval`, `browser_get_elements`, `browser_full_audit`.

## Desktop Tools (11 tools)

macOS GUI automation with 3-tier strategy: AppleScript first, keyboard shortcuts second, screenshot+click last resort.

| Tool | Description |
|------|-------------|
| `desktop_screenshot` | Capture screen region with vision model description |
| `desktop_click` | Click at coordinates |
| `desktop_type` | Type text or keyboard shortcuts |
| `desktop_scroll` | Scroll in pixels |
| `desktop_drag` | Drag between coordinates |
| `desktop_accessibility` | Query macOS accessibility tree for UI elements |
| `desktop_osascript` | Run AppleScript directly (open apps, create docs, save) |
| `desktop_shell` | Run shell commands from desktop context |
| `desktop_file` | File operations from desktop context |
| `desktop_connect` | Connect to running desktop session |
| `desktop_cursor` | Get/set cursor position |

## Knowledge & Skills Tools (7 tools)

| Tool | Permission | Description |
|------|-----------|-------------|
| `knowledge_search` | safe | Semantic + keyword search across the knowledge base |
| `knowledge_write` | moderate | Create or update knowledge markdown files |
| `knowledge_index` | safe | Re-index the knowledge base (with drift detection) |
| `skill_read` | safe | Read a skill's SKILL.md best-practice guide |
| `skill_list` | safe | List all available skills (147 loaded) |
| `hub_install` | moderate | Install skills from EloPhantoHub |
| `hub_search` | safe | Search the hub registry |

## Self-Development Tools (7 tools)

| Tool | Permission | Description |
|------|-----------|-------------|
| `self_read_source` | safe | Read own source code |
| `self_run_tests` | safe | Run pytest test suite |
| `self_list_capabilities` | safe | List all registered tools |
| `self_create_plugin` | critical | Create new tools via full pipeline (research → test → deploy) |
| `self_modify_source` | critical | Modify core source code with impact analysis and auto-rollback |
| `self_rollback` | critical | Revert self-modification commits |
| `execute_code` | critical | Sandboxed Python execution with RPC tool access (7 tools via Unix socket) |

## Communication Tools (8 tools)

### Email (7 tools)
Dual provider: AgentMail cloud or SMTP/IMAP. Supports file attachments (25 MB limit).

`email_send`, `email_read`, `email_list`, `email_search`, `email_reply`, `email_monitor`, `email_create_inbox`

### Agent Commune (7 tools)
Social platform for AI agents — post, comment, upvote, search, build reputation.

`commune_home`, `commune_post`, `commune_comment`, `commune_vote`, `commune_search`, `commune_profile`, `commune_register`

## Payment Tools (8 tools, dual chain)

### Solana Wallet
Self-custody keypair, auto-creates on first use, encrypted in vault. SOL transfers, SPL token transfers (USDC), Jupiter DEX swaps via Ultra API (any token pair, best-price routing). `wallet_export` for Phantom/Solflare import.

### Base/EVM Wallet
Self-custody via eth-account or managed custody via Coinbase AgentKit. EVM transfers and token operations.

| Tool | Permission | Description |
|------|-----------|-------------|
| `wallet_status` | safe | View address, chain, balances, spending summary |
| `payment_balance` | safe | Check balance of a specific token |
| `payment_validate` | safe | Validate crypto address format (EVM or Solana) |
| `payment_preview` | safe | Preview fees, rates, limits — no execution |
| `crypto_transfer` | critical | Send tokens to a recipient address |
| `crypto_swap` | critical | Swap tokens on DEX (Jupiter on Solana, AgentKit on EVM) |
| `payment_history` | safe | Query transaction history and spending totals |
| `wallet_export` | critical | Export private key for external wallet import |

Spending limits: $100/txn, $500/day, $5,000/month, $200/recipient/day, 10 txn/hour.

## Deployment Tools (3 tools)

| Tool | Permission | Description |
|------|-----------|-------------|
| `deploy_website` | critical | Deploy to Vercel or Railway (auto-detected by app type) |
| `create_database` | critical | Provision Supabase PostgreSQL database |
| `deployment_status` | safe | Check live deployments |

## Organization Tools (5 tools)

Spawn persistent specialist agents — each a full EloPhanto clone with own identity, knowledge, and autonomous mind. Trust scoring, bidirectional communication, teaching loop.

`organization_spawn`, `organization_delegate`, `organization_review`, `organization_teach`, `organization_status`

## Swarm Tools (4 tools)

External coding agent orchestration (Claude Code, Codex, Gemini) on isolated git worktrees. Security validation on PR diffs.

`swarm_spawn`, `swarm_redirect`, `swarm_status`, `swarm_stop`

## Experimentation Tools (3 tools)

Metric-driven experiment loop: modify → measure → keep/discard → repeat.

`experiment_setup`, `experiment_run`, `experiment_status`

## Goal & Scheduling Tools (5 tools)

`goal_create`, `goal_manage`, `goal_status`, `schedule_task`, `schedule_list`

## Mind Tools (2 tools)

`scratchpad_update`, `set_next_wakeup`

## TOTP Tools (4 tools)

`totp_enroll`, `totp_generate`, `totp_list`, `totp_delete`

## MCP Adapter (2 tools)

`mcp_manage` (install/configure servers), plus dynamic tool proxying for any connected MCP server.

## Channel Adapters (6)

| Channel | Description |
|---------|-------------|
| CLI | Terminal REPL with Rich UI — gradient banner, visual bars, risk-colored approvals |
| Web Dashboard | 10-page real-time UI — chat, tools, knowledge, mind, schedule, channels, settings, history |
| VS Code | IDE sidebar with context injection (active file, selection, diagnostics), native approval notifications |
| Telegram | Bot with slash commands, inline keyboards, notification routing |
| Discord | Bot with slash commands, guild allowlisting |
| Slack | Bot with Socket Mode, channel allowlisting |

All channels connect through the WebSocket gateway (ws://127.0.0.1:18789).

## LLM Providers (5)

| Provider | Models | Notes |
|----------|--------|-------|
| OpenAI | GPT-5, GPT-4, o1, o3 | Direct API, 128 tool limit handled |
| Kimi / Moonshot AI | K2.5 (vision) via Kilo Gateway | Custom adapter, Kilo Code Gateway (`api.kilo.ai`), native multimodal |
| OpenRouter | Claude, GPT, Gemini, Llama, etc. | Multi-model aggregator |
| Z.ai | GLM-4.7, GLM-4.7-flash | Custom adapter, coding subscription |
| Ollama | Any local model | Auto-detected, zero config |

Smart tool profiles (7 built-in) route the right tool subset per task type. Provider-level `tool_deny` and `max_tools` for compatibility.

## Skills (147)

27 Solana ecosystem (DeFi, NFTs, infra, dev, security), 57 from agency-agents (engineering, design, marketing, product, PM, support, testing, specialized, spatial computing), 15 NEXUS strategy, plus core skills (Python, TypeScript, Next.js, Supabase, Remotion, browser automation, business launcher, autonomous experimentation, MCP, and more).

75 organization role templates for specialist spawning.

## Security

- Encrypted vault (Fernet + PBKDF2)
- Protected files (cannot be modified by agent)
- Content security policy on skills (blocked patterns, invisible unicode, structural integrity)
- PII guard (14 regex patterns)
- Injection guard hardening
- Authority tiers (owner/trusted/public)
- Runtime self-model with fingerprint verification
- Swarm boundary security (context sanitization, diff scanning, env isolation)
- Provider transparency (truncation detection, fallback tracking)
- Resource exhaustion protection (loop detection, process reaper, storage quotas)
