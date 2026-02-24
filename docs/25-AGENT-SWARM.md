# Agent Swarm — Orchestrate Claude Code, Codex & Gemini CLI

EloPhanto turns you into a one-person dev team. Instead of running Claude Code or Codex by hand, EloPhanto spawns them, writes their prompts with full business context from your knowledge vault, monitors progress, redirects agents that go off track, runs multi-model code review, and pings you on Telegram when PRs are ready to merge.

You talk to EloPhanto. EloPhanto manages the fleet.

## The Problem with Raw CLI Agents

Context windows are zero-sum. Fill one with code and there's no room for business context. Fill one with customer history and there's no room for the codebase.

Every CLI agent — Claude Code, Codex, Gemini CLI — sees code. None of them see your business. None of them know what your customer said in yesterday's call, which approach failed last time, or why that feature was deprioritized. You end up copy-pasting context into every prompt, babysitting terminals, and manually checking if agents finished.

EloPhanto fixes this with separation of concerns:

```
You ← conversation → EloPhanto (business context + orchestration)
                         │
                         ├── Claude Code  (code context only)
                         ├── Codex        (code context only)
                         ├── Gemini CLI   (code context only)
                         └── ... N agents in parallel
```

EloPhanto holds your knowledge vault — meeting notes, customer data, past decisions, what shipped, what failed — and translates that into precise prompts for each coding agent. The coding agents stay focused on code. EloPhanto stays at the strategy level.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     EloPhanto                        │
│  Knowledge │ Vault │ Memory │ Goals │ Scheduler      │
│  Browser   │ Email │ Identity │ Multi-Channel        │
├─────────────────────────────────────────────────────┤
│               Agent Swarm Manager                    │
│  spawn · monitor · redirect · review · notify        │
├──────────┬──────────┬──────────┬────────────────────┤
│ Process 1│ Process 2│ Process 3│  ...                │
│ Claude   │ Codex    │ Gemini   │                     │
│ Code     │          │ CLI      │                     │
├──────────┴──────────┴──────────┴────────────────────┤
│  git worktree per agent → isolated branches → PRs    │
└─────────────────────────────────────────────────────┘
```

Each coding agent runs in its own:
- **Managed process** — EloPhanto spawns it via `tmux` for persistence, automatic logging, and mid-task redirection. If EloPhanto restarts, agent sessions survive.
- **Git worktree** — isolated branch per agent. No merge conflicts between parallel agents.
- **Independent environment** — own `node_modules`, builds, and test runs.

## Configuration

Add to `config.yaml`:

```yaml
agents:
  enabled: true
  worktree_base: ../worktrees        # where to create isolated branches
  max_concurrent: 4                  # limited by RAM (~3GB per agent)
  monitor_interval: 600              # check every 10 minutes
  max_retries: 3                     # auto-respawn on failure
  notify_channels: [telegram, cli]   # where to send "PR ready" notifications

  profiles:
    claude:
      command: "claude --model claude-opus-4-6 --dangerously-skip-permissions -p"
      strengths: [frontend, git-operations, fast-iteration, quick-fixes]
    codex:
      command: "codex --model gpt-5.3-codex -c 'model_reasoning_effort=high' --dangerously-bypass-approvals-and-sandbox"
      strengths: [backend, complex-bugs, multi-file-refactors, reasoning]
    gemini:
      command: "gemini --model gemini-2.5-flash -p"
      strengths: [ui-design, css, visual-polish]

  done_criteria:
    pr_created: true
    ci_passed: true
    review_passed: true
```

Prerequisites: install the CLI agents you want (`claude`, `codex`, `gemini`), plus `tmux` and `gh` (GitHub CLI).

## Workflow

### 1. Describe the Task

Talk to EloPhanto from any channel — CLI, Telegram, Discord, Slack:

```
You: "The agency customer from yesterday's call wants to reuse configs
     across their team. Build a template system."
```

EloPhanto has your meeting notes in its knowledge vault. Zero explanation needed — it already knows the customer, their tier, their current setup, and what they're paying for.

### 2. EloPhanto Spawns an Agent

EloPhanto picks the right agent for the task, creates an isolated worktree, enriches the prompt with business context, and spawns the agent:

```bash
# EloPhanto does this automatically:
git worktree add ../worktrees/feat-templates -b feat/templates origin/main
cd ../worktrees/feat-templates && pnpm install

tmux new-session -d -s "agent-templates" \
  "codex --model gpt-5.3-codex \
   --dangerously-bypass-approvals-and-sandbox \
   'Implement a configuration template system for team sharing.
    Customer: Acme Agency (enterprise tier, 12 users).
    Their current config structure: { ... pulled from knowledge vault ... }
    Requirements: save existing configs as templates, edit, duplicate, share.
    Stack: Next.js 16, Prisma, PostgreSQL.
    Tests: unit + E2E. Include screenshots for UI changes.
    When done: git push && gh pr create --fill'"
```

The task is tracked in a registry so EloPhanto can monitor it:

```json
{
  "id": "feat-templates",
  "agent": "codex",
  "session": "agent-templates",
  "branch": "feat/templates",
  "status": "running",
  "started_at": "2026-02-24T10:30:00Z",
  "retries": 0
}
```

### 3. Automated Monitoring

EloPhanto's scheduler checks all running agents every 10 minutes. The check is deterministic — no LLM calls, near-zero cost:

- **Process alive?** — Is the agent session still running?
- **PR created?** — `gh pr list --head feat/templates`
- **CI passed?** — `gh pr checks`
- **Reviews passed?** — All AI reviewers approved?

On failure, EloPhanto decides the next action using business context:

| Failure | Response |
|---------|----------|
| Agent crashed | Respawn with same prompt |
| CI failed (lint/types) | Respawn with error output appended to prompt |
| CI failed (tests) | Analyze failure, refine prompt, respawn |
| Wrong approach | Redirect agent mid-task (see below) |
| Needs human decision | Escalate to Telegram/Slack |

### 4. Mid-Task Redirection

When an agent goes off track, EloPhanto redirects it without killing it. This is the key advantage — EloPhanto has context the coding agent doesn't:

```bash
# Agent building the wrong thing
tmux send-keys -t agent-templates \
  "Stop. The customer wants to save EXISTING configs as templates,
   not create templates from scratch. Reuse the ConfigSnapshot type
   in src/types/config.ts." Enter

# Agent needs data it doesn't have
tmux send-keys -t agent-templates \
  "Here's the customer's actual config structure: { ... }
   Match this schema exactly." Enter
```

EloPhanto makes these calls using knowledge the coding agent never had — customer history, meeting notes, what was tried before, why it failed.

### 5. Multi-Model Code Review

Every PR gets reviewed by multiple AI models before you see it. They catch different things:

| Reviewer | What it catches |
|----------|----------------|
| **Codex** | Edge cases, logic errors, race conditions. Lowest false-positive rate |
| **Gemini Code Assist** | Security issues, scalability problems. Free tier |
| **Claude Code** | Validates what others flag. Best at architectural concerns |

All three post comments directly on the PR via `gh api`. EloPhanto orchestrates the reviews in parallel.

### 6. Notification

Only when ALL criteria pass does EloPhanto notify you:

```
Telegram: "PR #341 ready for review.
  ✓ CI passed (lint, types, unit, E2E)
  ✓ Codex review: approved
  ✓ Gemini review: approved
  ✓ Claude review: approved
  ✓ Screenshots attached
  Branch: feat/templates"
```

Your review takes 5 minutes. Many PRs you merge from the screenshot alone.

### 7. Cleanup

A daily scheduled task removes merged worktrees and clears completed entries from the task registry. No manual housekeeping.

## Agent Selection

EloPhanto auto-routes tasks to the best agent:

| Task Type | Agent | Why |
|-----------|-------|-----|
| Backend logic, complex bugs | Codex | Deepest reasoning, most thorough |
| Frontend, fast iteration | Claude Code | Faster, better at component work |
| UI/UX design, CSS polish | Gemini | Strongest design sensibility |
| Git operations, PRs | Claude Code | Cleanest git workflow handling |
| Multi-file refactors | Codex | Best cross-codebase reasoning |
| Quick fixes, single-file | Claude Code | Speed |
| Design → implementation | Gemini → Claude Code | Gemini designs, Claude builds |

## Parallel Execution

Multiple agents work simultaneously on different features:

```
agent-templates     (codex)          → feat/templates       → PR #341
agent-billing-fix   (codex)          → fix/billing-webhook   → PR #342
agent-dashboard     (gemini→claude)  → feat/dashboard        → PR #343
agent-docs          (claude)         → docs/api-reference    → PR #344
agent-sentry-fix    (codex)          → fix/null-pointer      → PR #345
```

### Hardware Requirements

Each agent needs ~3GB RAM (worktree + dependencies + build + tests):

| Machine | RAM | Concurrent Agents |
|---------|-----|-------------------|
| MacBook Air M2 | 16GB | 3–4 |
| Mac Mini M4 | 32GB | 8–10 |
| Mac Studio M4 Max | 128GB | 30+ |
| Linux server (cloud) | 64GB | 15–20 |

## Self-Improving Prompts

When agents succeed (CI passes, reviews pass, human merges), EloPhanto logs the prompt pattern:
- "This prompt structure works for billing features"
- "Codex needs type definitions upfront for this repo"
- "Always include test file paths — agents skip tests without them"

When agents fail, EloPhanto doesn't respawn with the same prompt. It reads the failure with full business context and writes a better one:

- **Ran out of context?** → "Focus only on these three files"
- **Wrong direction?** → "Customer wanted X, not Y. Here's what they said in the call"
- **Missing info?** → "The schema changed last week. Here's the migration file"

Over time, EloPhanto's prompts get better because it remembers what shipped. The reward signals are: CI passing, reviews passing, human merge. Any failure triggers the learning loop.

## Proactive Work Discovery

EloPhanto doesn't wait for you to assign tasks:

- **Morning** — Scans error monitoring → spawns agents for new bugs
- **After meetings** — Scans meeting notes in knowledge vault → flags feature requests → spawns agents
- **Evening** — Scans git log → updates changelog and customer-facing docs
- **Continuous** — Monitors email inbox → routes customer requests to agents

You take a walk after a customer call. Come back to Telegram: *"7 PRs ready for review. 3 features, 4 bug fixes."*

## Why EloPhanto, Not Raw CLI Agents

| | Raw CLI Agent | EloPhanto |
|---|---|---|
| **Context** | Code only | Code + business + customers + history |
| **Monitoring** | Watch terminals manually | Automated checks, zero cost |
| **Failure recovery** | Kill and restart | Context-aware retry with refined prompt |
| **Notifications** | None | Telegram, Discord, Slack, CLI |
| **Agent selection** | You decide every time | Auto-routed by task type and past success |
| **Parallel work** | Manual process management | Tracked registry, auto-cleanup |
| **Learning** | Starts fresh every time | Prompt patterns persist across sessions |
| **Proactive** | Never | Scans errors, meetings, inbox |
| **Mid-task steering** | Copy-paste into terminal | Automatic redirection with business context |
| **Code review** | Manual or single model | Multi-model parallel review |

## Related

- [02-ARCHITECTURE.md](02-ARCHITECTURE.md) — EloPhanto system layers
- [03-TOOLS.md](03-TOOLS.md) — Shell execution and tool system
- [05-KNOWLEDGE-SYSTEM.md](05-KNOWLEDGE-SYSTEM.md) — Knowledge vault for business context
- [13-GOAL-LOOP.md](13-GOAL-LOOP.md) — Background goal execution
- [22-RECOVERY-MODE.md](22-RECOVERY-MODE.md) — Agent health monitoring
