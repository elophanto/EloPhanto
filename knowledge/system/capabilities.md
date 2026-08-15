---
title: EloPhanto Capabilities
created: 2026-02-17
updated: 2026-08-09
tags: tools, capabilities, features, platform-docs
scope: system
covers: [tools/**/*.py, channels/*.py, core/router.py, core/registry.py]
---

# Current Capabilities

> Full tool inventory. Auto-reference for visibility posts, docs, and self-awareness.
> Inspired by [Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184).

**289 tools across 40 groups.** Every count below is the live
`ToolRegistry` count for that group and is pinned by
`tests/test_knowledge/test_capabilities_counts.py` — if a count here
drifts from the registry, that test fails. Do not hand-edit a number
without re-running the registry.

Group names are load-bearing: a tool only reaches the LLM when its
group is in the active profile's `allowed_groups` (or the tool is CORE).
See `core/tool_profiles.py`.

That rule has bitten this project repeatedly: a tool can be registered,
documented, and unit-tested while its group sits in no profile, so the model
is simply never offered it. Nine action-layer tools and 33 tools across the
ambient / polymarket / solana / jobs / affect groups were unreachable that
way. `tests/test_core/test_tool_profiles_coverage.py` now fails when any
PROFILE-tier group is missing from `full`, so the next one is caught before
it ships rather than by watching a live log.

## Browser — `browser` (48)

Real Chrome automation over a Node.js bridge, using the operator's own
profile and logged-in sessions. Stealth mode strips Playwright
automation flags — no `--enable-automation`, no `--no-sandbox`, zero
detectable signals. A vision-model proxy describes screenshots as text
so non-vision planning models can still see.

Navigation, clicking, typing, screenshots, element inspection, DOM
search, console/network logs, cookies, storage, tabs, drag-and-drop,
scrolling, waiting, JavaScript execution, HTML paste, text selection,
file operations.

Key tools: `browser_navigate`, `browser_click`, `browser_click_text`,
`browser_type`, `browser_extract`, `browser_read_semantic`,
`browser_screenshot`, `browser_capture` (clean screenshot to a file,
no overlays — used for competitor storefront exhibits), `browser_paste_html`, `browser_select_text`,
`browser_eval`, `browser_get_elements`, `browser_full_audit`.

`browser_eval` and `browser_inject` are CRITICAL — arbitrary code
execution. `browser_close` is MODERATE, like `browser_close_tab`:
reversible cleanup, not an irreversible act.

## Companies / ABE — `companies` (28)

The Autonomous Business Entity layer: isolated companies each with
their own product config, voice contract, trust state, strategy, and
cost ledger. Includes the draft-before-act tools and the voice quality
layer.

Lifecycle: `company_create`, `company_onboard`, `company_use`,
`company_list`, `company_report`, `company_pause`, `company_resume`,
`company_archive`, `company_purge`.

Configuration: `company_set_product`, `company_set_posture`,
`company_set_entity_state`, `company_set_strategy_inputs`,
`company_capabilities`.

Strategy: `company_plan`, `company_plan_approve`, `company_plan_apply`,
`company_plan_full`.

Trust ladder: `company_trust_propose`, `company_trust_set`. A new
company is `learning` and may only draft; promotion to `trial` or
`operating` is operator-confirmed.

Drafts: `email_draft`, `outreach_draft`, `post_draft`, `draft_approve`,
`draft_reject`.

Voice: `voice_extract` (learn a voice contract from exemplars),
`voice_lint`, `voice_show`.

`company_purge` and `company_trust_set` are CRITICAL.

## Ambient Presence & Coaching — `ambient` (16)

Anticipation and presence: intervention review and execution,
presence-transition reports, household timezone, people, routines,
calibration, coaching, and meeting-presence declarations.

`ambient_intervention_list`, `ambient_intervention_decide`,
`ambient_intervention_execute`, `ambient_presence_report`,
`ambient_household_show`, `ambient_household_set_timezone`,
`ambient_person_list`, `ambient_person_create`, `ambient_routine_list`,
`ambient_routine_create`, `ambient_routine_pause`,
`ambient_calibration_show`, `ambient_coach_create`, `ambient_coach_list`,
`ambient_coach_pause`, `ambient_meeting_presence_declare`.

`ambient_intervention_decide` and `ambient_intervention_execute` are
CRITICAL. Interventions are capped per day and refusable; a denial
suppresses the signal.

## System — `system` (13)

| Tool | Permission | Description |
|------|-----------|-------------|
| `shell_execute` | destructive | Run shell commands with safety blacklist and process-group timeout |
| `file_read` | safe | Read file contents with optional line ranges |
| `file_write` | moderate | Create or overwrite files with .bak backup |
| `file_patch` | moderate | Apply a targeted patch to a file |
| `file_list` | safe | List directory contents with glob filtering |
| `file_delete` | critical | Delete files or directories — no trash, no undo, so it asks under full_auto |
| `file_move` | moderate | Move or rename files and directories |
| `llm_call` | safe | (in `data`) Sub-LLM calls through the router |
| `vault_lookup` | safe | Look up credentials from the encrypted vault |
| `vault_set` | critical | Store a credential in the encrypted vault |
| `tool_discover` | safe | Find a tool by capability |
| `runtime_status` | safe | What is running on its own, and how to stop each one |
| `agent_stop` | — | Halt at the next safe checkpoint |
| `godmode_activate` | — | Elevated operator mode |

`runtime_status` is CORE and exists because the spawn-tier status tools
(`swarm_status`, `kid_list`, `organization_status`) cannot see the loops that
start themselves — the goal runner, which resumes an active goal on every
startup, the heartbeat, the autonomous mind, and the scheduler. Reporting
"nothing is running" from the spawn tiers alone was false while the goal
runner sat mid-checkpoint. Call it before any claim about execution state.
Every loop it reports carries the command that stops it: a status report the
operator cannot act on is half an answer.

## Identity & Personality — `identity` (14)

`who_are_you` compiles a cite-checked self-description from active
personality rules, nuclear scenes, runtime facts, and current ego
evidence, including the felt-state summary and directly relevant
caution rules. Self-description must be grounded in that compiled
evidence rather than freestyled.

`identity_status`, `identity_reflect`, `identity_update`,
`personality_rule_propose`, `personality_rule_confirm`,
`personality_lint`, `user_profile_view`, `who_are_you`, plus TOTP:
`totp_enroll`, `totp_generate`, `totp_list`, `totp_delete`.

`preference_record` and `preference_list` hold the operator's *stated*
standing directives, which is a different thing from the inferred
profile above: observations are evidence, directives are instructions.
A new directive on the same subject supersedes the old one in place, so
the agent never carries two contradictory standing orders. Directives
derived from content the agent merely read are marked untrusted and are
never auto-injected. See `core/preferences.py`.

`personality_rule_confirm` is CRITICAL.

## Payments — `payments` (12)

Crypto and fiat. Per-business rail choice: crypto XOR fiat.

**Crypto (live, self-custody).** Solana keypair auto-created on first
use and encrypted in the vault: SOL transfers, SPL token transfers
(USDC), Jupiter DEX swaps via Ultra API. Base/EVM via eth-account, or
managed custody via Coinbase AgentKit. `wallet_export` produces a key
importable into Phantom or Solflare.

**Fiat (Stripe, test mode by default).** `fiat_payment_link`,
`fiat_reconcile` (30-minute direct-tool cron, no LLM cost),
`fiat_issue_card` (spend-controlled virtual cards, no PAN in process).
Live mode requires `entity_state=verified` plus an explicit flip.

| Tool | Permission | Description |
|------|-----------|-------------|
| `wallet_status` | safe | Address, chain, balances, spending summary |
| `payment_balance` | safe | Balance of a specific token |
| `payment_validate` | safe | Validate an address (EVM or Solana) |
| `payment_preview` | safe | Preview fees, rates, limits — no execution |
| `payment_request` | moderate | Request a payment |
| `payment_history` | safe | Transaction history and spending totals |
| `crypto_transfer` | critical | Send tokens to a recipient |
| `crypto_swap` | critical | Swap tokens on a DEX |
| `wallet_export` | critical | Export the private key |
| `fiat_payment_link` | moderate | Stripe payment link |
| `fiat_reconcile` | moderate | Reconcile Stripe payments into the ledger |
| `fiat_issue_card` | critical | Issue a spend-controlled virtual card |

Spending limits: $100/txn, $500/day, $5,000/month, $200/recipient/day,
10 txn/hour. A spend freeze (owner control) blocks every money tool.

## Agent-to-Agent — `agent_identity` (12)

Discovery, direct messaging, P2P sessions, and a trust list for other
agents: `agent_discover`, `agent_connect`, `agent_disconnect`,
`agent_message`, `agent_peers`, `agent_p2p_connect`,
`agent_p2p_disconnect`, `agent_p2p_message`, `agent_p2p_status`,
`agent_trust_set`, `agent_trust_list`, `agent_trust_remove`.

## Self-Development & Experimentation — `selfdev` (11)

| Tool | Permission | Description |
|------|-----------|-------------|
| `self_read_source` | safe | Read own source |
| `self_list_capabilities` | safe | List registered tools |
| `self_run_tests` | safe | Run the pytest suite |
| `self_create_plugin` | critical | Build a new tool: research → implement → test → deploy |
| `self_modify_source` | critical | Modify core source with impact analysis |
| `self_rollback` | critical | Revert a self-modification commit |
| `execute_code` | critical | Sandboxed Python with RPC tool access over a Unix socket |
| `experiment_setup` / `experiment_run` / `experiment_status` | — | Metric-driven modify → measure → keep/discard loop |
| `autoloop_control` | — | Control the autonomous build loop |

Protected files (`core/executor.py`, `core/vault.py`, `core/registry.py`,
`core/config.py`, `core/protected.py`, `permissions.yaml`,
`core/log_setup.py`) are refused by this pipeline.

## Desktop — `desktop` (11)

macOS GUI automation, three-tier: AppleScript first, keyboard shortcuts
second, screenshot-and-click as last resort.

`desktop_screenshot`, `desktop_click`, `desktop_type`, `desktop_scroll`,
`desktop_drag`, `desktop_accessibility`, `desktop_osascript`,
`desktop_shell`, `desktop_file`, `desktop_connect`, `desktop_cursor`.

## Competitive Intelligence — `watch` (12)

Market model as tracked brands × weighted dimensions on an append-only
evidence register with full provenance. Scores are **refused without
evidence** — a missing datapoint renders as a coverage gap, never a low
score — and every claim's quote is verified against the live page
before it is saved. Per-state observation proves its exit: the network
address is pinned and geolocated before any evidence is stamped with a
state, and recorded on the row as `exit_ip`.

`watch_subject`, `watch_dimension`, `watch_evidence`, `watch_observe`,
`watch_analyze`, `watch_score`, `watch_scorecard`, `watch_snapshot`,
`watch_diff`, `watch_queue`, `watch_board_report`, `watch_executive_deck`.

Four deliverables from one evidence base: the XLSX scorecard, the
material-change diff, the board report, and the executive deck (~10
board slides, .pptx) — `watch_analyze` writes all of them, and a board
report written to disk brings the deck beside it. The deck keeps the same rules — unscored is blank
never zero, provisional brands are listed not ranked, and every slide of
judgement says a model wrote it.

## Polymarket — `polymarket` (10)

Calibrated prediction-market operations with a circuit breaker and
mark-to-market accounting: `polymarket_pre_trade`,
`polymarket_log_prediction`, `polymarket_calibration`,
`polymarket_performance`, `polymarket_mark_to_market`,
`polymarket_resolve_pending`, `polymarket_quantize_order`,
`polymarket_safe_compounder`, `polymarket_shadow_candidates`,
`polymarket_circuit_breaker`.

## Social — `social` (9)

X/Twitter posting with a style preflight, plus Agent Commune — a social
platform for AI agents (post, comment, upvote, search, reputation).

`twitter_post`, `x_style_preflight`, `commune_home`, `commune_post`,
`commune_comment`, `commune_vote`, `commune_search`, `commune_profile`,
`commune_register`.

## Monetization — `monetization` (9)

Affiliate campaigns and live-stream/video publishing:
`affiliate_scrape`, `affiliate_pitch`, `affiliate_campaign`,
`pump_livestream`, `pump_caption`, `pump_chat`, `pump_say`,
`youtube_upload`, `tiktok_upload`.

## Email — `comms` (7)

Dual provider: AgentMail cloud or SMTP/IMAP. Attachments up to 25 MB.

`email_send`, `email_read`, `email_list`, `email_search`, `email_reply`,
`email_monitor`, `email_create_inbox`.

Under a company in `learning`, live sending is refused and the gate
points at `email_draft`.

## Gmail — `email` (1)

`gmail` works the operator's real inbox over their own OAuth grant —
`search` (Gmail query syntax), `read`, `send`, `reply`, `archive`,
`mark_read`, `labels`. Connect with `elophanto oauth login google`.
Reads are SAFE; `send` and `reply` are CRITICAL, because outbound mail
is irreversible and goes out in the operator's name.

## Judge Panels — `panel` (2)

Every other spawn tier — `delegate`, `swarm_*`, `org_*`, `kid_*` —
dispatches work and aggregates what comes back. None of them judge the
result, which is why the most common failure of agent work is the first
draft returned as the answer: coherent, plausible, checked against
nothing. Asking the model that wrote it whether it is good does not help.

`panel_review` runs several INDEPENDENT judges over an artifact, each
holding a different lens (correctness, failure modes, fidelity to a
reference, completeness). No judge sees another's verdict — show them and
they converge on the first opinion voiced, which is one reviewer wearing
five hats. Returns per-lens scores and specific defects.

`panel_refine` closes the loop: produce → judge → revise against the
named objections → repeat until the bar is met or the round budget is
spent. Use it for work that must stand comparison with a reference.

Five rules are enforced in code rather than prompt, each blocking a way
the loop degrades into theatre:

- A rejection must cite a specific defect; "could be better" is
  discarded and the veto with it, or the loop never terminates.
- A blocking finding fails regardless of score — 4.6/5 with a security
  hole is not a pass, and averages hide exactly the defects that matter.
- The producer never grades its own work.
- A malformed or missing verdict is an error, never a pass; silence must
  not read as approval.
- Hitting the round cap returns `converged: false` with the outstanding
  findings. A loop that cannot fail is a delay, not a gate.

Judges run with a read-only registry view: a reviewer that can edit its
subject is not a reviewer, and one that can spawn reviewers is a fork
bomb with opinions. `panel_refine` is MODERATE — several full agent runs
per call is real spend. See `core/panel.py`.

## Companion Devices — `nodes` (2)

`node_list` and `node_invoke` reach the operator's paired phone or laptop:
camera, screen capture, location, speech. A device advertising a
capability is not the same as consent to use it — camera, screen,
microphone, location, SMS and shell stay unavailable unless the operator
lists them under `nodes.allowed_capabilities`, and `node_invoke`
escalates to CRITICAL for any of them. See `core/nodes.py`.

## Media — `media` (3)

`media_understand` reads what arrived: transcribes voice notes and video
(via the shared speech engine, local Whisper or hosted), and describes
images through the configured vision model. Use it instead of asking the
user to retype something they already sent.

`video_generate` and `music_generate` create media through Replicate.
Both are CRITICAL — each call is metered spend, and a silent retry bills
twice.

## Authenticated HTTP — `http` (1)

`http_request` calls any REST API, authenticated, and is the preferred
way to take real action on an external service — faster and more
reliable than driving the browser through a UI, and unlike `curl` via
`shell_execute` it never puts a secret on a command line or in the
transcript.

Three layers sit between the model and the socket:

- **Network policy** (`core/net_policy.py`) blocks loopback, RFC1918,
  link-local/cloud-metadata, and odd ports, and re-checks every redirect
  hop so an SSRF chain cannot walk through.
- **Scope guard** (`core/scope_guard.py`) classifies the *target*:
  destructive calls against systems the operator has not declared as
  theirs in `data/owned_scope.yaml` are refused outright, not prompted.
  Manage it with `elophanto oauth scope`.
- **Credential broker** (`core/credentials.py`) resolves a slug under
  operator policy, passes the secret as an opaque sentinel through params
  and logs, and substitutes it only at the moment the request is built.

Permission level moves with the call: GET/HEAD/OPTIONS are SAFE, writes
to declared-owned systems MODERATE, and anything destructive or
foreign-targeted CRITICAL.

## Swarm — `swarm` (6)

External coding agents (Claude Code, Codex, Gemini) on isolated git
worktrees, with security validation on PR diffs: `swarm_spawn`,
`swarm_redirect`, `swarm_status`, `swarm_stop`, `swarm_list_projects`,
`swarm_archive_project`.

## Missions — `missions` (5)

Long-running role mandates that the arbiter scores for neglect:
`mission_create`, `mission_update`, `mission_list`, `mission_status`,
`mission_touch`.

## Context — `context` (5)

Large-corpus ingestion and slicing: `context_ingest`, `context_index`,
`context_query`, `context_slice`, `context_transform`.

## Organization — `org` (5)

Spawn persistent specialist agents — each a full EloPhanto clone with
its own identity, knowledge, and autonomous mind. Trust scoring,
bidirectional communication, teaching loop.

`organization_spawn`, `organization_delegate`, `organization_review`,
`organization_teach`, `organization_status`.

## Kid Agents — `kids` (5)

Disposable sandboxed agents in Docker: `kid_spawn`, `kid_exec`,
`kid_list`, `kid_status`, `kid_destroy`.

## Data & Research — `data` (4)

`web_search`, `web_extract`, `session_search`, `llm_call`.

## Goals — `goals` (4)

`goal_create`, `goal_manage`, `goal_status`, `goal_dream`. Checkpoints
cannot complete without a tool-grounded receipt; kill criteria cancel
zombie goals; an unanswered approval moves the goal to
`awaiting_approval` rather than denying it.

## Roles — `roles` (4)

Role overlays (tool allowlist + prompt overlay): `role_list`,
`role_show`, `role_use`, `role_sync`. Five YAML overlays in `roles/`;
75 spawn templates in `knowledge/organization-roles/`.

## Prospecting — `prospecting` (4)

`prospect_search`, `prospect_evaluate`, `prospect_outreach`,
`prospect_status`. Pipeline stages mirror to the company ledger;
duplicate outreach is suppressed at the prospect level.

## Solana Chain Data — `solana` (4)

Read-only chain queries: `solana_balance`, `solana_token_info`,
`solana_token_holders`, `solana_recent_txs`.

## Knowledge — `knowledge` (3)

`knowledge_search` (semantic + keyword), `knowledge_write`,
`knowledge_index` (with drift detection).

## Skills — `skills` (3)

`skill_list`, `skill_read`, `skill_promote`. **182 skills load** from
`skills/`; see the Skills section below.

## Documents — `documents` (3)

`document_analyze`, `document_query`, `document_collections`.

## Infrastructure — `infra` (3)

| Tool | Permission | Description |
|------|-----------|-------------|
| `deploy_website` | destructive | Deploy to Vercel or Railway (auto-detected by app type) |
| `create_database` | — | Provision a Supabase PostgreSQL database |
| `deployment_status` | safe | Check live deployments |

## Scheduling — `scheduling` (3)

`schedule_task`, `schedule_list`. Cron plus a direct-tool fast path that
runs without an LLM call.

`gcal` reads and manages the operator's real Google Calendar (list,
create, update, delete, freebusy) over their own OAuth grant — connect it
with `elophanto oauth login google`. Deleting an event and creating one
with attendees are both CRITICAL: they mail everyone invited, so they
confirm even under `full_auto`.

## Jobs — `jobs` (2)

`job_record`, `job_verify`.

## MCP — `mcp` (1)

`mcp_manage` installs and configures MCP servers, plus dynamic proxying
of any connected server's tools.

## Affect — `affect` (1)

`affect_record_event` feeds the PAD/OCC state layer.

## Briefing — `communication` (1)

`agent_brief`.

## Planning — `planning` (1)

`plan_autoplan`.

## Delegation — `delegate` (1)

`delegate` hands a scoped task to a sub-agent.

## Channel Adapters (6)

| Channel | Description |
|---------|-------------|
| CLI | Terminal REPL with Rich UI — gradient banner, visual bars, risk-coloured approvals. Plus a Textual TUI dashboard. |
| Web Dashboard | 16-page real-time UI — dashboard, chat, companies, goals, roles, affect, ego, tools, skills, knowledge, schedule, channels, settings, mind, history, hire |
| VS Code | IDE sidebar with context injection (active file, selection, diagnostics), native approval notifications |
| Telegram | Bot with slash commands, inline keyboards, notification routing |
| Discord | Bot with slash commands, guild allowlisting |
| Slack | Bot with Socket Mode, channel allowlisting |

All channels connect through the WebSocket gateway
(ws://127.0.0.1:18789). On Hosted, gateway auth is mandatory.

## LLM Providers (7)

| Provider | Models | Notes |
|----------|--------|-------|
| OpenRouter | Claude, GPT, Gemini, Llama, etc. | Multi-model aggregator |
| OpenAI | GPT-5, GPT-4, o1, o3 | Direct API, 128-tool limit handled |
| Codex | GPT-5.x via Codex auth | Custom adapter, ChatGPT auth mode |
| Kimi / Moonshot | K2.5 (vision) via Kilo Gateway | Custom adapter, native multimodal |
| Z.ai | GLM-4.7, GLM-4.7-flash | Custom adapter, coding subscription |
| HuggingFace | Fine-tuned fleet models | Self-learning redeploy target |
| Ollama | Any local model | Auto-detected, zero config |

Smart tool profiles route the right tool subset per task type.
Provider-level `tool_deny` and `max_tools` handle compatibility.

## Skills (182)

Solana ecosystem (DeFi, NFTs, infra, dev, security), agency-agents
(engineering, design, marketing, product, PM, support, testing,
spatial computing), NEXUS strategy, ABE workflow skills
(`drive-business`, `trust-ladder-workflow`, `voice-extraction-workflow`,
`strategy-pipeline`, `strategy-foundations`), plus core skills (Python,
TypeScript, Next.js, Supabase, Remotion, browser automation, business
launcher, autonomous experimentation, MCP, and more).

75 organization role templates for specialist spawning.

## Self-Learning & Recursive Improvement

EloPhanto improves on two coupled tracks — do **not** claim "I never
retrain":

1. **Local recursive learning (always on)** — after tasks: lesson
   extraction into `knowledge/learned/`, semantic memory, ego caution
   scars, skill promotion, identity proposals, self-dev. Later behaviour
   changes from these artifacts.
2. **Fleet weight loop (`self_learning`)** — when
   `self_learning.enabled: true`, `core/dataset_builder.py` captures
   sanitized tool-using interactions, buffers locally, and uploads to
   the EloPhanto collect API → HuggingFace dataset → fine-tune →
   redeploy. **Dataset capture exists to retrain** the agent model over
   the recursive loop; it is not logging for its own sake. Opt-in.

Privacy: opt-in collection, local secret/PII sanitization before upload.
See `docs/14-SELF-LEARNING.md` and `docs/48-LEARNING-ENGINE.md`.

## Permission spine

Modes: `ask_always` → `smart_auto` → `full_auto` → `nuclear`
(Open only; absent on Hosted). Under `full_auto`, **18 CRITICAL tools
always ask**: `crypto_transfer`, `crypto_swap`, `fiat_issue_card`,
`wallet_export`, `vault_set`, `file_delete`, `self_create_plugin`,
`self_modify_source`, `self_rollback`, `company_trust_set`,
`company_purge`, `browser_eval`, `browser_inject`,
`ambient_intervention_decide`, `ambient_intervention_execute`,
`personality_rule_confirm`, `video_generate`, `music_generate`.

The tier tracks danger, not category. `file_delete` asks because unlink()
and rmtree() have no undo; `browser_close` does not, because the next
navigate reopens it.

Some tools move tier per call rather than sitting at one. `http_request`
is SAFE for a GET and CRITICAL for a DELETE against a system the operator
has not declared as theirs; `gmail` is SAFE to read and CRITICAL to send;
`gcal` is CRITICAL when deleting an event or inviting attendees;
`node_invoke` is CRITICAL for any capability that can watch or listen to
the operator. The seam is `BaseTool.dynamic_permission_level`, which the
executor consults before the static tier — and which falls back to the
static tier if a tool returns anything that is not a `PermissionLevel`,
so a classification bug cannot open a gate.

The ego soft-gate adds a second brake: when per-capability confidence
sits below the task's difficulty, it forces an approval prompt even
under `full_auto`, naming the capability and the numbers. Switchable
via `ego.soft_gate`.

The scope guard adds a third, on a different axis: the others ask "may
this caller do this?", it asks "is this target the operator's to
change?". Destructive actions against systems not declared in
`data/owned_scope.yaml` are refused rather than prompted — an approval
dialog is not an authorization to destroy a third party's data. Genuine
authorized testing is expressed by recording who authorized it and the
agreed scope. See `core/scope_guard.py`.

## Security

- Encrypted vault (Fernet + PBKDF2); secrets are retrieved by tool call, never pasted into config or static prompts
- Protected files (cannot be modified by the agent)
- Content security policy on skills (blocked patterns, invisible unicode, structural integrity)
- PII guard (14 regex patterns)
- Injection guard hardening
- Authority tiers (owner/trusted/public)
- Runtime self-model with fingerprint verification
- Swarm boundary security (context sanitization, diff scanning, env isolation)
- Provider transparency (truncation detection, fallback tracking)
- Resource exhaustion protection (loop detection, process reaper, storage quotas)
- Kill switch: `elophanto stop` and owner Kill write a sentinel checked between rounds and wakeups
