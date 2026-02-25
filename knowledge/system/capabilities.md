---
title: EloPhanto Capabilities
created: 2026-02-17
updated: 2026-02-18
tags: tools, capabilities, features
scope: system
---

# Current Capabilities

## System Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `shell_execute` | destructive | Run shell commands with safety blacklist |
| `file_read` | safe | Read file contents with optional line ranges |
| `file_write` | moderate | Create or overwrite files with .bak backup |
| `file_list` | safe | List directory contents with glob filtering |
| `file_delete` | destructive | Delete files or directories |
| `file_move` | moderate | Move or rename files and directories |
| `llm_call` | safe | Make sub-LLM calls through the router |
| `vault_lookup` | safe | Look up credentials from the encrypted vault |
| `vault_set` | critical | Store a credential in the encrypted vault |

## Browser Tools (47 tools via Node.js bridge)

Real Chrome automation using the user's profile. Tools cover: navigation, clicking, typing, screenshots, element inspection, DOM search, console/network logs, cookies, storage, tabs, drag-and-drop, scrolling, waiting, and JavaScript execution. Key tools:

- `browser_navigate`, `browser_go_back`
- `browser_click`, `browser_click_text`, `browser_click_at`
- `browser_type`, `browser_press_key`, `browser_select_option`
- `browser_extract`, `browser_read_semantic`, `browser_screenshot`
- `browser_get_elements`, `browser_full_audit`, `browser_deep_inspect`
- `browser_get_console`, `browser_get_network`, `browser_get_cookies`
- `browser_new_tab`, `browser_list_tabs`, `browser_switch_tab`
- `browser_wait_for_selector`, `browser_eval`

## Knowledge & Skills Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `knowledge_search` | safe | Semantic + keyword search across the knowledge base |
| `knowledge_write` | moderate | Create or update knowledge markdown files |
| `knowledge_index` | safe | Re-index the knowledge base |
| `skill_read` | safe | Read a skill's SKILL.md best-practice guide |
| `skill_list` | safe | List all available skills |

## Self-Development Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `self_read_source` | safe | Read own source code |
| `self_run_tests` | safe | Run pytest test suite |
| `self_list_capabilities` | safe | List all registered tools |
| `self_create_plugin` | critical | Create new tools via full pipeline (research → test → deploy) |
| `self_modify_source` | critical | Modify core source code with impact analysis and auto-rollback |
| `self_rollback` | critical | Revert self-modification commits |

## Scheduling Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `schedule_task` | moderate | Schedule recurring ("every hour") or one-time ("in 5 minutes") tasks |
| `schedule_list` | safe | View, enable, disable, or delete scheduled tasks |

## Payment Tools (7 tools, dual wallet provider)

Crypto wallet management with spending limits, audit trail, and approval flow. Two wallet providers:

- **Local wallet (default)** — Self-custody via `eth-account`, zero config, auto-creates on first use. Supports transfers, no swaps.
- **Coinbase CDP (optional)** — Managed custody via AgentKit, gasless transactions, DEX swaps. Requires CDP API keys.

| Tool | Permission | Description |
|------|-----------|-------------|
| `wallet_status` | safe | View wallet address, chain, token balances, spending summary |
| `payment_balance` | safe | Check balance of a specific token (default: USDC) |
| `payment_validate` | safe | Validate crypto address format (EVM or Solana) |
| `payment_preview` | safe | Preview fees, exchange rates, spending limits — no execution |
| `crypto_transfer` | critical | Send tokens from agent wallet to a recipient address |
| `crypto_swap` | critical | Swap tokens on DEX — requires agentkit provider |
| `payment_history` | safe | Query transaction history and spending totals |

Spending limits: $100/txn, $500/day, $5,000/month, $200/recipient/day, 10 txn/hour, duplicate detection.

## Skills (27 loaded)

Best-practice guides loaded before tasks. Categories: Python, TypeScript/Node.js, browser automation, file management, research, Next.js, Supabase, Prisma, shadcn, React, MCP, web app testing, UI/design.

## LLM Providers

- **Ollama**: Local models, auto-detected
- **Z.ai/GLM**: Cloud models (glm-4.7, glm-4.7-flash)
- **OpenRouter**: Cloud models (Claude, GPT, Gemini, Llama)

## Interfaces

- **CLI**: `elophanto chat` (interactive), `elophanto init`, `elophanto vault`, `elophanto schedule`, `elophanto skills`, `elophanto rollback`, `elophanto telegram`
- **Telegram**: Full bot interface with commands (/status, /tasks, /approve, /deny, /plugins, /mode, /budget), notifications, inline keyboards. Starts automatically with `elophanto chat` when enabled in config and bot token is in the vault. Can also run standalone with `elophanto telegram`.

Note: Users can run commands via `./start.sh <command>` (handles venv activation automatically) or by manually activating the venv (`source .venv/bin/activate`) and running `elophanto <command>`. When telling users to run commands, prefer `./start.sh <command>` for simplicity. When the user stores a Telegram token, tell them to restart — Telegram will auto-start alongside the CLI.

## Security

- **Encrypted vault** (Fernet + PBKDF2) for credentials
- **Protected files** that the agent cannot modify (core/executor.py, core/vault.py, etc.)
- **Configurable permissions** via permissions.yaml (per-tool overrides)
- **Log redaction** strips API keys and secrets from all log output
- **Approval queue** persists across restarts (database-backed)
- **Permission modes**: ask_always, smart_auto, full_auto
