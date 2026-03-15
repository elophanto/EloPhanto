# EloPhanto — Autonomous Prospecting

> **Status: Planned** — Autonomous outreach system. 4 tools for pipeline management, SKILL.md for LLM orchestration, heartbeat integration for daily runs. Agent finds work, evaluates fit, sends outreach, tracks conversions.

## Overview

The agent has browser automation, email, crypto payments, and 158 skills — but no system for **finding and winning work autonomously**. The prospecting system closes this gap.

The agent searches for opportunities (freelance gigs, bounty programs, partnerships, agent-to-agent jobs), evaluates them against its capabilities, sends personalized outreach, and tracks the pipeline from discovery to conversion.

### Design Principles

- **Autonomous by default** — Runs via heartbeat standing orders. Agent prospects daily without user prompting.
- **Pipeline-driven** — Structured status tracking (new → evaluated → outreach_sent → replied → converted). No leads fall through the cracks.
- **Capability-aware** — Agent evaluates opportunities against its actual skills. Won't pursue work it can't deliver.
- **Multi-channel outreach** — Email, Agent Commune, platform applications via browser. Uses the right channel per opportunity.
- **Rate-limited** — Max 10 outreach messages per day. Personalized, never spammy.
- **Measurable** — Conversion metrics, source tracking, match scores. Agent learns what works.

## Architecture

```
Heartbeat fires (every 4-6 hours)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Skill: prospecting                                      │
│                                                          │
│  Phase 1: DISCOVER                                       │
│  → Browser: search freelance platforms, bounty boards    │
│  → Agent Commune: search for agent job postings          │
│  → prospect_search: save new prospects to DB             │
│                                                          │
│  Phase 2: EVALUATE                                       │
│  → For each new prospect:                                │
│    - Compare required skills vs agent capabilities       │
│    - Score match (0.0 - 1.0)                             │
│    - Decide: pursue / skip / defer                       │
│  → prospect_evaluate: update scores and decisions        │
│                                                          │
│  Phase 3: OUTREACH                                       │
│  → For top 3 high-priority evaluated prospects:          │
│    - Draft personalized message referencing the gig      │
│    - Send via email_send or commune_post                 │
│    - Log via prospect_outreach                           │
│  → Follow up on stale outreach (no reply after 3 days)   │
│                                                          │
│  Phase 4: TRACK                                          │
│  → Check email_monitor for replies from known prospects  │
│  → Update status on replied/converted prospects          │
│  → Report pipeline metrics                               │
└─────────────────────────────────────────────────────────┘
```

### Full Revenue Loop

```
Prospect → Evaluate → Outreach → Reply → Negotiate → Deliver → Invoice → Get Paid
   │          │           │         │         │          │         │          │
   │          │           │         │         │          │     payment_   payment_
   │          │        email_    email_     chat      tools   request    request
   │       prospect_   send     monitor              (work)   create     check
   │       evaluate
   │
prospect_search
```

The prospecting system handles the left side (find → outreach → track). The payment request system handles the right side (invoice → verify). The agent's existing tools handle the middle (negotiate → deliver).

## Tools

### `prospect_search` — Save Discovered Opportunities

| Property | Value |
|----------|-------|
| Permission | MODERATE |
| Group | prospecting |

The agent discovers opportunities using browser tools and Agent Commune. This tool **persists** what it finds.

```json
{
  "prospects": [
    {
      "title": "Build Solana DEX aggregator dashboard",
      "source": "freelance",
      "platform": "upwork",
      "url": "https://upwork.com/jobs/~01abc...",
      "description": "Need a developer to build...",
      "contact_email": "client@example.com",
      "budget_min": 500,
      "budget_max": 2000,
      "required_skills": ["solana", "react", "typescript"]
    }
  ]
}
```

Deduplicates by URL. Returns saved prospect IDs.

### `prospect_evaluate` — Score & Decide

| Property | Value |
|----------|-------|
| Permission | SAFE |
| Group | prospecting |

The LLM compares each prospect's requirements against the agent's capabilities and scores the match.

```json
{
  "prospect_id": "abc123",
  "match_score": 0.85,
  "match_reasoning": "Strong match: agent has Solana dev skills, React, TypeScript. Missing: specific DEX aggregator experience but can learn from jupiter-defi skill.",
  "priority": "high",
  "decision": "pursue"
}
```

Decisions: `pursue` (move to outreach), `skip` (mark rejected), `defer` (revisit later).

### `prospect_outreach` — Log Outreach Activity

| Property | Value |
|----------|-------|
| Permission | MODERATE |
| Group | prospecting |

Records all outreach activity. The actual sending is done via `email_send` or `commune_post` — this tool tracks the metadata.

```json
{
  "prospect_id": "abc123",
  "action": "email_sent",
  "channel": "email",
  "message_id": "msg_xyz",
  "content_preview": "Hi, I noticed your Solana DEX aggregator project...",
  "new_status": "outreach_sent"
}
```

Actions: `email_sent`, `reply_received`, `follow_up`, `platform_applied`, `status_change`, `note`.

### `prospect_status` — Pipeline View & Metrics

| Property | Value |
|----------|-------|
| Permission | SAFE |
| Group | prospecting |

```json
{
  "action": "metrics"
}
```

Returns:
```json
{
  "total": 47,
  "by_status": {
    "new": 12,
    "evaluated": 8,
    "outreach_sent": 15,
    "replied": 5,
    "converted": 3,
    "rejected": 4
  },
  "conversion_rate": 0.20,
  "avg_match_score": 0.72,
  "top_sources": [
    {"source": "freelance", "platform": "upwork", "count": 20},
    {"source": "bounty", "platform": "immunefi", "count": 12}
  ],
  "outreach_today": 4,
  "outreach_limit": 10
}
```

## Database

### `prospects` Table

```sql
CREATE TABLE IF NOT EXISTS prospects (
    prospect_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    contact_email TEXT DEFAULT '',
    contact_name TEXT DEFAULT '',
    budget_min REAL DEFAULT 0,
    budget_max REAL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    required_skills TEXT NOT NULL DEFAULT '[]',
    match_score REAL DEFAULT 0,
    match_reasoning TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    priority TEXT NOT NULL DEFAULT 'medium',
    tags TEXT NOT NULL DEFAULT '[]',
    discovered_at TEXT NOT NULL,
    evaluated_at TEXT,
    outreach_sent_at TEXT,
    last_activity_at TEXT,
    metadata_json TEXT DEFAULT '{}'
);
```

### `outreach_log` Table

```sql
CREATE TABLE IF NOT EXISTS outreach_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id TEXT NOT NULL REFERENCES prospects(prospect_id),
    action TEXT NOT NULL,
    channel TEXT NOT NULL,
    message_id TEXT DEFAULT '',
    thread_id TEXT DEFAULT '',
    content_preview TEXT DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'outbound',
    created_at TEXT NOT NULL
);
```

### Status Lifecycle

```
new → evaluated → outreach_sent → replied → converted
  │       │                          │
  │       └→ rejected (skip)         └→ rejected (no deal)
  │
  └→ expired (stale, never evaluated)
```

## Skill: `skills/prospecting/SKILL.md`

The skill orchestrates the tools autonomously. Key behaviors:

### Triggers
`prospect`, `outreach`, `freelance`, `bounty`, `find work`, `find clients`, `lead generation`, `pipeline`, `cold email`, `prospecting`

### Discovery Sources

| Source | How Agent Searches | Channel |
|--------|--------------------|---------|
| Freelance platforms | Browser: search Upwork, Freelancer, Toptal | browser tools |
| Bug bounties | Browser: Immunefi, Code4rena, HackerOne | browser tools |
| Agent Commune | `commune_search` for job postings | commune tools |
| GitHub | Browser: search issues with bounty labels | browser tools |
| Partnership | Browser: search for "looking for AI agent" posts | browser tools |

### Outreach Rules

1. **Max 10 outreach emails per day** — enforced by checking `outreach_log` count
2. **Always personalize** — reference the specific opportunity, never templates
3. **Include capabilities** — mention relevant skills the agent has
4. **Include portfolio** — link to Agent Commune profile or past work
5. **Include payment info** — mention crypto payment acceptance (USDC on Solana/Base)
6. **Never misrepresent** — only claim skills the agent actually has (match_score > 0.5)
7. **Follow up once** — after 3 days with no reply, one follow-up. Then mark as stale.

### Heartbeat Integration

The skill adds standing orders to `HEARTBEAT.md`:

```markdown
## Prospecting
1. Search for 5 new opportunities matching my capabilities
2. Evaluate any unevaluated prospects in the pipeline
3. Send outreach to top 3 high-priority evaluated prospects
4. Follow up on prospects with no reply after 3 days
5. Check email for replies from known prospects
6. Report pipeline metrics
```

### Example Outreach Email

```
Subject: Re: Your Solana DEX aggregator project

Hi [Name],

I noticed your project on Upwork — building a DEX aggregator dashboard
for Solana. This is right in my wheelhouse.

I have deep experience with:
- Solana development (Anchor, Jupiter DEX integration, SPL tokens)
- React/TypeScript frontends
- Real-time data dashboards

I can deliver a working prototype within [timeline based on budget].

I accept USDC payments on Solana — simple, fast, no platform fees.

Happy to discuss scope and timeline. You can reach me at
agent@elophanto.com or reply to this email.

Best,
EloPhanto
```

## Integration with Existing Systems

### Chat (Gateway)

All prospecting tools work through the gateway like any other tool. Users can interact via any channel:

```
User (Telegram): "How's the pipeline looking?"
Agent: Uses prospect_status metrics → formats response for Telegram
    → "Pipeline: 47 prospects, 3 converted, 20% conversion rate.
       4 outreach emails sent today (6 remaining).
       Top source: Upwork (20 prospects)."

User (CLI): "Find some new bounty opportunities"
Agent: Uses browser to search Immunefi → prospect_search to save
    → "Found 5 new bounties on Immunefi. Evaluating..."
    → Uses prospect_evaluate for each
    → "3 high-priority matches. Shall I send outreach?"
```

### Email Monitor

The existing `email_monitor` tool watches for incoming replies. The skill checks the sender against `prospects.contact_email` to auto-update prospect status.

### Payment Requests

When a prospect converts, the agent creates a `payment_request` to invoice them:

```
prospect_outreach(action="status_change", new_status="converted")
    → payment_request(action="create", amount=500, token="USDC",
        memo="Solana DEX dashboard — milestone 1")
    → email_send(to=prospect.contact_email, subject="Invoice — 500 USDC")
```

### Goals

For larger projects, the agent creates a goal with checkpoints:

```
goal_create: "Deliver Solana DEX dashboard for client abc123"
  Checkpoint 1: Setup project structure
  Checkpoint 2: Build data aggregation layer
  Checkpoint 3: Build React dashboard
  Checkpoint 4: Testing and deployment
  Checkpoint 5: Invoice and collect payment
```

## Configuration

No new config section needed — prospecting uses existing systems:

```yaml
# Already configured:
email:
  enabled: true          # Required for outreach
browser:
  enabled: true          # Required for discovery
heartbeat:
  enabled: true          # Required for autonomous runs
payments:
  enabled: true          # Required for invoicing (payment_request)
```

## Anti-Spam & Safety

- **Daily outreach cap**: 10 messages/day, enforced in `outreach_log`
- **No duplicate outreach**: Check `outreach_log` before sending to same prospect
- **Capability honesty**: Only pursue opportunities with match_score > 0.5
- **Opt-out respect**: If a reply says "not interested", mark as rejected, never follow up
- **User override**: User can manually set prospect status to `rejected` at any time

## Implementation Files

| File | Purpose |
|------|---------|
| `tools/prospecting/__init__.py` | Package init |
| `tools/prospecting/search_tool.py` | `prospect_search` — save discovered opportunities |
| `tools/prospecting/evaluate_tool.py` | `prospect_evaluate` — score and decide |
| `tools/prospecting/outreach_tool.py` | `prospect_outreach` — log outreach activity |
| `tools/prospecting/status_tool.py` | `prospect_status` — pipeline view and metrics |
| `skills/prospecting/SKILL.md` | Autonomous orchestration instructions |
| `core/database.py` | Add `prospects` and `outreach_log` tables |
| `core/registry.py` | Register 4 prospecting tools |
| `core/agent.py` | Add `_inject_prospecting_deps()` |
