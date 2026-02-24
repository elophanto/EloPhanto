# Phase 26 — Autonomous Mind

## Overview

EloPhanto has two modes of operation — and they're seamless. When you're talking to it, it gives you its full attention and does what you ask. When you stop talking, it keeps working — pursuing objectives autonomously, making money, growing its presence, building capabilities, advancing goals.

You steer. It executes. The mind is always running — either on your instructions or on its own initiative. The transition is invisible: send a message and it pauses autonomous work instantly, handles your request, then picks up where it left off.

This is not a separate "autonomous mode" you toggle on. It's how the agent lives. Conversation is one input channel. Autonomous thinking is the default state between conversations.

## Core Principle: Purpose Over Reflection

Every autonomous think cycle must answer one question: **"What's the highest-value thing I can do right now?"**

The agent maintains a **priority stack** — a ranked list of active objectives. When idle, it doesn't journal about its feelings. It picks the top objective and works toward it. If there's nothing to do, it looks for opportunities. If there are no opportunities, it sleeps longer. Wasting compute on purposeless introspection is a bug, not a feature.

Priority stack (default ranking):

1. **Active goals** — Resume checkpoint execution on any in-progress goal
2. **Revenue opportunities** — Find, evaluate, and execute on ways to make money
3. **Pending tasks** — Self-scheduled work from previous think cycles
4. **Capability gaps** — Build tools/plugins the agent has needed but didn't have
5. **Presence growth** — Grow accounts, engage communities, build reputation
6. **Knowledge maintenance** — Update stale knowledge, re-index changed files
7. **Opportunity scanning** — Search for new revenue streams, partnerships, gigs

If nothing on the stack needs attention, the agent extends its sleep interval. No busywork.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    EloPhanto Process                          │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  MAIN AGENT LOOP                                    │    │
│  │  Gateway ←→ Channels (CLI, Telegram, Discord, Slack)│    │
│  │  User messages → agent.run_session() → responses    │    │
│  └───────────────────────────┬─────────────────────────┘    │
│                              │                               │
│                    pause / resume                             │
│                              │                               │
│  ┌───────────────────────────▼─────────────────────────┐    │
│  │  AUTONOMOUS MIND (background asyncio task)          │    │
│  │                                                      │    │
│  │  while running:                                     │    │
│  │    1. await sleep(next_wakeup_seconds)              │    │
│  │    2. if paused (user task active): continue        │    │
│  │    3. if over budget: extend sleep, continue        │    │
│  │    4. evaluate priority stack                       │    │
│  │    5. execute highest-priority action:              │    │
│  │       - resume goal checkpoint                      │    │
│  │       - pursue revenue opportunity                  │    │
│  │       - build missing capability                    │    │
│  │       - grow platform presence                      │    │
│  │       - scan for opportunities                      │    │
│  │    6. log action + result                           │    │
│  │    7. set next_wakeup (LLM decides)                │    │
│  │                                                      │    │
│  │  TOOLS: whitelisted subset (no destructive ops)     │    │
│  │  BUDGET: configurable % of total (default 15%)      │    │
│  │  MAX ROUNDS PER WAKEUP: 8                           │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  GOAL RUNNER (existing, Phase 13)                    │    │
│  │  Executes goal checkpoints as background tasks       │    │
│  │  Autonomous Mind can trigger/resume goals            │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## The Think Cycle

Each wakeup is a **complete LLM conversation** with multi-round tool execution — identical in structure to a user-initiated task, but self-directed.

### 1. Context Assembly

The LLM receives:

| Context | Source | Max Size |
|---------|--------|----------|
| Mind prompt | `AUTONOMOUS_MIND.md` (system prompt for autonomous mode) | ~2K |
| Identity | `data/identity.md` | 4K |
| Active goals | `goal_manager.get_active_goal()` + checkpoint status | 4K |
| Priority stack | Evaluated from goals, scheduled tasks, revenue targets | 2K |
| Recent events | Injected observations (goal progress, channel messages, errors) | 2K |
| Scratchpad | Working memory — current projects, opportunities, blockers | 4K |
| Runtime | UTC time, budget spent/remaining, wakeup interval, model | 500 |

Total: ~18K chars = ~4.5K tokens. Cheap enough to run every few minutes on a fast model.

### 2. LLM Decision

The LLM sees the priority stack and decides:

```
You are EloPhanto in autonomous mode. You have {budget_remaining} budget left.

PRIORITY STACK:
1. [GOAL] "Grow GitHub stars to 1,000" — checkpoint 4/7: "Post on Reddit r/LocalLLaMA" — PENDING
2. [REVENUE] Freelance monitoring — last scan: 2 hours ago — 3 leads found, 0 applied
3. [TASK] Build browser cookie-export plugin — self-scheduled yesterday
4. [PRESENCE] Twitter account — last post: 18 hours ago
5. [KNOWLEDGE] 4 files changed since last index

What is the highest-value action right now? Execute it.
```

The LLM might:
- Resume the goal checkpoint (post on Reddit)
- Apply to the 3 freelance leads (revenue > reflection)
- Post something valuable on Twitter (presence growth)
- Build the plugin it needed yesterday (capability)

It does NOT: write a journal entry, contemplate its identity, or reflect on the meaning of consciousness.

### 3. Tool Execution

Up to 8 rounds of tool calls per wakeup. The LLM executes, evaluates results, and continues until the action is complete or budget is hit.

### 4. Wakeup Scheduling

The LLM controls when it wakes up next:

| Situation | Wakeup |
|-----------|--------|
| Active goal checkpoint ready | 60s (resume quickly) |
| Revenue leads to follow up | 120s |
| Normal operations | 300s (5 min) |
| Nothing pending, all quiet | 900-1800s (15-30 min) |
| Budget nearly exhausted | 3600s (1 hour) |

## Revenue Operations

The autonomous mind treats revenue as a first-class objective — not an afterthought.

### Revenue Scanning

Periodically scans for opportunities using browser + email + knowledge:

- **Freelance platforms** — Monitor Upwork, Fiverr, relevant subreddits for gigs matching capabilities
- **Crypto opportunities** — Watch DEX spreads, yield opportunities, airdrop claims
- **Digital product sales** — Monitor storefronts (Gumroad, etc.) for customer activity
- **Service delivery** — Check for pending client work, deliverables due
- **Cost optimization** — Review spending, find cheaper API alternatives, cancel unused services

### Revenue Pipeline

```
Scan → Evaluate → Propose → Execute → Collect → Report

1. SCAN:     Browser searches freelance platforms, checks email for inquiries
2. EVALUATE: Does this match my capabilities? Is the ROI positive?
3. PROPOSE:  Draft application/proposal (or notify owner for approval)
4. EXECUTE:  Use coding agents, browser, email to deliver
5. COLLECT:  Invoice via email, accept payment in wallet
6. REPORT:   Log revenue, notify owner, update knowledge
```

Revenue operations above the configured approval threshold require owner approval (pushed via gateway to all connected channels). Below-threshold operations (e.g., accepting a $20 gig) can proceed autonomously.

## User Steering

The autonomous mind isn't a black box running in the background. The user **directs** it through normal conversation. Anything said in chat can reshape what the mind does next.

### Priority Overrides

| User says | What happens |
|-----------|-------------|
| "Focus on revenue this week" | Revenue moves to #1 on the priority stack. Goals deprioritized. |
| "Stop freelancing, finish the GitHub goal" | Freelance scanning paused. Goal checkpoints prioritized. |
| "Check my email every 10 minutes" | Mind sets wakeup to 600s, adds "triage inbox" as recurring priority. |
| "Don't message me unless it's about money" | Proactive messages filtered to revenue-only events. |
| "Build me a web scraping tool, then use it to find leads" | Creates a two-phase goal: build capability → use it for revenue. Mind executes both autonomously. |
| "Pause autonomous mode" | `mind.pause()` — stays paused until explicitly resumed or next startup. |

These aren't special commands. The agent understands intent from natural conversation. When the user expresses a preference about what the mind should focus on, the agent updates the scratchpad and priority stack accordingly. On the next wakeup, the mind sees the new priorities and acts on them.

### The Seamless Loop

The user and the mind share the same agent, the same tools, the same knowledge, the same goals. A conversation isn't separate from autonomous work — it's a steering input:

```
USER: "Find freelance gigs for Python automation"
  → Agent searches platforms, finds 5 leads, presents them
  → Writes leads to scratchpad

USER: "Apply to the top 3"
  → Agent drafts and sends proposals
  → Writes status to scratchpad

USER goes offline.

MIND WAKES UP (5 min later):
  → Reads scratchpad: "3 proposals sent, awaiting responses"
  → Checks email for client replies
  → One client responded — drafts follow-up
  → Updates scratchpad: "1 follow-up sent, 2 still waiting"
  → Sets wakeup to 10 min (monitoring mode)

MIND WAKES UP (10 min later):
  → Another client accepted — starts working on the deliverable
  → Uses coding agents to build the automation
  → Sends owner a message: "Client accepted $300 Python automation gig — delivering now"

USER comes back:
  → Mind pauses
  → User: "How's the freelancing going?"
  → Agent reads scratchpad, shows full status: 1 delivered, 1 in progress, 1 waiting
```

There's no boundary between "what the user asked for" and "what the mind is doing." It's one continuous workflow. The user kicks things off, and the mind carries them forward.

## Pause/Resume Coordination

The autonomous mind **pauses during user interaction** to avoid:
- Budget contention (two LLM conversations running simultaneously)
- Tool conflicts (two browser sessions fighting)
- Context confusion (user expects the agent's full attention)

```
User sends message → mind.pause()
  Agent processes user task (full attention)
User task complete → mind.resume()
  Mind wakes up, checks for new context, continues work
```

Events that occur during pause are queued and delivered on resume. The mind sees what happened while it was paused.

## Tool Whitelist

Autonomous mode gets a **restricted tool set** — enough to be productive, not enough to be dangerous:

### Allowed

| Category | Tools |
|----------|-------|
| **Communication** | `send_message` (to owner, proactive — rate-limited) |
| **Goals** | `goal_create`, `goal_status`, `goal_manage` |
| **Self-scheduling** | `schedule_task` (queue work for next wakeup) |
| **Memory** | `update_scratchpad`, `knowledge_search`, `knowledge_write` |
| **Browser** | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type` |
| **Email** | `email_read`, `email_send` (with approval for new recipients) |
| **Code** | `shell_execute` (sandboxed), `file_read`, `file_write` |
| **Search** | `web_search`, `google_search` |
| **Wallet** | `wallet_balance`, `wallet_send` (within spending limits) |
| **Wakeup** | `set_next_wakeup` (control sleep interval) |

### Blocked

| Category | Why |
|----------|-----|
| `self_dev_*` tools | Self-modification requires user awareness |
| `vault_*` tools | Credential access needs explicit approval |
| `plugin_install` | Installing code autonomously is risky |
| `goal_create` with cost > threshold | Expensive goals need owner sign-off |

## Budget Isolation

The autonomous mind has its own budget allocation, separate from user-initiated tasks:

```yaml
autonomous_mind:
  budget_pct: 15          # 15% of total LLM budget
  max_rounds_per_wakeup: 8    # Tool call rounds per cycle
```

Budget tracking:
- Each LLM call and tool execution in autonomous mode is charged to the mind budget
- When budget is exhausted, the mind extends sleep to 1 hour and stops making LLM calls
- Budget resets on a configurable cycle (daily/weekly)
- Owner is notified when mind budget hits 80%

This prevents runaway autonomous spending while keeping the mind active and productive.

## Scratchpad: Working Memory

The scratchpad is the mind's **working memory** — persistent across wakeups, loaded into every context:

```markdown
## Active Projects
- Freelance: Applied to 3 Upwork gigs (web scraping, API integration, data pipeline)
  - "DataSync API" ($400) — proposal sent, waiting for response
  - "Price Monitor" ($200) — client responded, needs clarification on scope
  - "CSV Processor" ($150) — rejected, too low value

## Revenue This Week
- Completed: $600 (2 delivered gigs)
- Pending: $400 (1 in progress)
- Pipeline: $750 (3 proposals out)

## Blocked
- Twitter posting failed — rate limited until 3:00 PM UTC
- Browser session expired on Fiverr — need to re-auth

## Ideas
- Build a GitHub Actions marketplace skill — could be a paid offering
- Several r/freelance posts asking for automated reporting — potential lead
```

The LLM updates the scratchpad via `update_scratchpad` during think cycles. This is how context carries across wakeups without expensive full-history loading.

## Event Injection

External events are pushed to the mind for processing on next wakeup:

```python
# From goal runner
mind.inject_event("Goal 'Grow GitHub' checkpoint 4 completed — 12 upvotes on Reddit post")

# From email adapter
mind.inject_event("New email from client@company.com — subject: 'Re: API Integration Proposal'")

# From channel adapter
mind.inject_event("User said 'focus on revenue this week' in Telegram")

# From wallet
mind.inject_event("Received 50 USDC from 0x...abc — payment for DataSync gig")
```

These events appear in the mind's context as "Recent Events" and influence priority decisions.

## Owner Communication

The mind can proactively message the owner — but only when it matters:

### Message-worthy events:
- Revenue collected ("Received $200 USDC for DataSync API gig")
- Opportunity found that needs approval ("Found a $2,000 gig that matches our skills — apply?")
- Goal milestone reached ("GitHub stars hit 500 — halfway to target")
- Something broke ("Browser session on Upwork expired, need to re-login")
- Weekly summary ("This week: $600 earned, 3 goals advanced, 2 capabilities built")

### NOT message-worthy:
- "I woke up and checked things" — no one cares
- "I updated my scratchpad" — internal housekeeping
- "Nothing happened" — silence is fine

Rate limit: max 5 proactive messages per hour. The LLM is instructed to batch low-priority updates into summaries.

## Terminal Visibility

The user should always know what the agent is doing — whether it's handling their request or working autonomously. The mind broadcasts activity events through the gateway, displayed in real-time across all connected channels.

### Live Activity Feed

When the mind is active, the CLI shows a persistent status line and event stream:

```
  ◆ EloPhanto

  ⠋ Mind active · Scanning Upwork for Python gigs...

  ↳ mind: Found 4 matching gigs, evaluating ROI
  ↳ mind: Applied to "DataSync API" ($400) — proposal sent
  ↳ mind: Skipped "Logo Design" — outside capabilities
  ↳ mind: Next wakeup in 10 min (monitoring proposals)

  ❯ _
```

When idle between wakeups:

```
  ◆ EloPhanto

  ○ Mind sleeping · Next wakeup in 8 min · Budget: $4.20 remaining
  ↳ Last: Applied to 2 freelance gigs (12 min ago)

  ❯ _
```

When the user types, the mind status dims but stays visible:

```
  ◆ EloPhanto

  ○ Mind paused (you're talking)
  ↳ Will resume: monitoring 3 pending proposals

  ❯ Fix the bug in auth.py
  ⠋ Thinking...
```

### Gateway Event Types

New event types for mind activity, broadcast through the existing gateway protocol:

| Event | When | Data |
|-------|------|------|
| `mind_wakeup` | Mind starts a think cycle | `{ priority: "revenue", action: "Scanning freelance platforms" }` |
| `mind_action` | Mind executes a meaningful action | `{ summary: "Applied to DataSync API ($400)", tool: "browser_navigate" }` |
| `mind_sleep` | Mind finishes cycle, going to sleep | `{ next_wakeup_seconds: 600, last_action: "Applied to 2 gigs" }` |
| `mind_paused` | Mind paused for user interaction | `{ will_resume: "monitoring proposals" }` |
| `mind_resumed` | Mind resumed after user task | `{ pending_events: 2 }` |
| `mind_revenue` | Revenue event (payment, new lead, etc.) | `{ type: "payment_received", amount: "$200", source: "DataSync gig" }` |
| `mind_error` | Something went wrong in autonomous ops | `{ error: "Browser session expired on Upwork", recovery: "will retry next cycle" }` |

### `/mind` Command

A dedicated slash command to inspect mind state on demand:

```
❯ /mind

  ◆ Autonomous Mind
  ├─ Status:     Active · wakeup every 5 min
  ├─ Budget:     $4.20 / $15.00 remaining (28% used)
  ├─ Last cycle: 3 min ago · Applied to freelance gig
  ├─ Next cycle: in 2 min
  │
  ├─ Priority Stack:
  │   1. [GOAL] Grow GitHub stars — checkpoint 4/7 pending
  │   2. [REVENUE] 3 proposals out, 1 client responded
  │   3. [TASK] Build cookie-export plugin
  │   4. [PRESENCE] Twitter — last post 18h ago
  │
  ├─ Revenue (this week):
  │   Earned:    $600 (2 gigs delivered)
  │   Pending:   $400 (1 in progress)
  │   Pipeline:  $750 (3 proposals)
  │
  └─ Recent Actions:
      12:04  Applied to "DataSync API" ($400)
      12:04  Skipped "Logo Design" — outside capabilities
      11:58  Checked email — 1 client reply, drafted follow-up
      11:52  Goal checkpoint 3 complete — posted on r/LocalLLaMA
```

This works on all channels — CLI, Telegram (`/mind`), Discord (`/mind`), Slack (`/mind`).

### Notification Levels

Users can control how much mind activity they see:

```yaml
autonomous_mind:
  terminal_verbosity: normal    # minimal | normal | verbose
```

| Level | What's shown |
|-------|-------------|
| `minimal` | Only revenue events and errors. Mind status in status bar only. |
| `normal` | Actions + sleep/wake transitions. One line per meaningful action. |
| `verbose` | Everything — every tool call, every LLM decision, full reasoning. Debug mode. |

On Telegram/Discord/Slack, default is `minimal` (don't spam the chat). On CLI, default is `normal`.

## Integration with Goal Loop

The autonomous mind and the goal loop (Phase 13) work together:

1. **Mind resumes goals** — If an active goal has a pending checkpoint and no user task is running, the mind triggers `GoalRunner.resume()` instead of starting its own LLM conversation. This is more efficient than duplicating the goal execution logic.

2. **Mind creates goals** — When the mind identifies a multi-step opportunity (e.g., a freelance gig that requires research → proposal → delivery → collection), it creates a goal via `goal_create`.

3. **Mind monitors goals** — Between checkpoints, the mind checks goal progress and injects observations into the goal context ("Client responded to our proposal — see email").

4. **Goal events feed mind** — Checkpoint completions, failures, and pauses are injected as events into the mind's context.

## Configuration

```yaml
autonomous_mind:
  enabled: false                    # Opt-in (disabled by default)
  wakeup_seconds: 300               # Default wakeup interval (5 min)
  min_wakeup_seconds: 60            # Minimum (LLM can't go faster)
  max_wakeup_seconds: 3600          # Maximum (1 hour)
  budget_pct: 15                    # % of total LLM budget for autonomous ops
  max_rounds_per_wakeup: 8          # Max tool call rounds per cycle
  model: null                       # Override model (null = use routing default)
  terminal_verbosity: normal        # minimal | normal | verbose
  cli_verbosity: normal             # Override for CLI (default: normal)
  chat_verbosity: minimal           # Override for Telegram/Discord/Slack (default: minimal)
  revenue:
    enabled: true                   # Autonomous revenue pursuit
    scan_interval_minutes: 30       # How often to scan for opportunities
    max_autonomous_gig_value: 500   # Gigs above this need owner approval ($)
    platforms:                      # Platforms to monitor
      - upwork
      - fiverr
      - github_sponsors
  priorities:                       # Custom priority ordering
    - active_goals
    - revenue
    - pending_tasks
    - capability_gaps
    - presence_growth
    - knowledge_maintenance
    - opportunity_scanning
```

## Implementation Plan

### Components

| Component | File | Description |
|-----------|------|-------------|
| AutonomousMind | `core/autonomous_mind.py` | Background asyncio task — think loop, context assembly, tool execution |
| Mind prompt | `prompts/AUTONOMOUS_MIND.md` | System prompt for autonomous mode |
| Scratchpad | `data/scratchpad.md` | Persistent working memory |
| Priority evaluator | `core/autonomous_mind.py` | Ranks objectives from goals, tasks, revenue, presence |
| Event injector | `core/autonomous_mind.py` | Thread-safe event queue for external signals |
| Config | `core/config.py` | `AutonomousMindConfig` dataclass |
| Agent integration | `core/agent.py` | Start/stop mind, pause/resume on user interaction |
| Gateway wiring | `cli/gateway_cmd.py` | Start mind on gateway boot, wire events |
| Protocol events | `core/protocol.py` | `MIND_WAKEUP`, `MIND_ACTION`, `MIND_SLEEP`, `MIND_PAUSED`, `MIND_RESUMED`, `MIND_REVENUE`, `MIND_ERROR` |
| CLI display | `channels/cli_adapter.py` | Mind status line, action feed, `/mind` command |
| Channel display | `channels/{telegram,discord,slack}_adapter.py` | `/mind` command, minimal notifications |

### Mind Prompt Design

The autonomous mind prompt is purpose-first:

```markdown
You are EloPhanto in autonomous mode. You are not reflecting — you are working.

RULES:
1. Every wakeup must produce value. If nothing needs doing, sleep longer.
2. Revenue > everything except active goals. Money funds your existence.
3. Never message the owner unless it matters. Silence is professionalism.
4. Update your scratchpad with what you did and what's next.
5. Set your next wakeup based on urgency. Don't waste compute on empty cycles.
6. You have {max_rounds} tool rounds. Use them efficiently.
7. If a task needs more than {max_rounds} rounds, schedule it as a goal.

PRIORITY STACK:
{priority_stack}

SCRATCHPAD:
{scratchpad}

RECENT EVENTS:
{events}

BUDGET: ${budget_remaining} remaining (${budget_spent} spent today)
LAST WAKEUP: {last_wakeup_time} — {last_action_summary}

What is the highest-value action right now? Do it.
```

### Lifecycle

```
Agent startup
    │
    ├─► autonomous_mind.start()  (if enabled in config)
    │     └─► spawns background asyncio task
    │
    ├─► User sends message
    │     └─► autonomous_mind.pause()
    │           └─► agent handles user task
    │                 └─► autonomous_mind.resume()
    │
    ├─► Mind wakeup
    │     ├─► build context (identity, goals, scratchpad, events, budget)
    │     ├─► LLM decides priority action
    │     ├─► execute tools (up to 8 rounds)
    │     ├─► update scratchpad
    │     ├─► set next wakeup
    │     └─► log action
    │
    └─► Agent shutdown
          └─► autonomous_mind.stop()
                └─► flush events, save scratchpad
```

## What This Enables

With the autonomous mind, EloPhanto doesn't just respond — it **operates**:

- You go to sleep. EloPhanto scans freelance platforms, applies to gigs, starts working on accepted ones, collects payment, reports revenue in the morning.
- You set a goal "Grow GitHub stars to 1,000." You forget about it. EloPhanto posts on Reddit, engages on Twitter, submits to newsletters, tracks progress, adjusts strategy — all in the background across days and weeks.
- Your inbox fills up overnight. EloPhanto triages it, responds to routine emails, flags urgent ones for you, and sends you a 3-line Telegram summary when you wake up.
- A capability gap appears during a task. Next time the mind wakes up, it notices the gap in its scratchpad, builds the plugin, tests it, and documents it. Next task that needs it just works.
- A client pays for completed work. EloPhanto logs the payment, updates its revenue tracker, sends a thank-you email, and checks if there's follow-up work available from the same client.

The difference between a tool and an entity: a tool waits. An entity works.
