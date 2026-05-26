---
name: trust-ladder-workflow
description: Per-company trust state procedure (learning / trial / operating). When a live outreach tool refuses, names the canonical draft replacement.
license: MIT
metadata:
  author: petr-royce
  version: "1.1.0"
  phase: 9
---

# Trust ladder workflow — DO NOT spam

Every ABE company has a 3-state trust ladder gating live outbound communication:

| State | Live outreach | Per-call approval | Default |
|---|---|---|---|
| `learning` | **REFUSED** — draft only | n/a | new companies |
| `trial` | allowed | MODERATE | promoted after voice approval |
| `operating` | allowed | within budget | mature |

## Triggers

- email_send / email_reply / prospect_outreach / twitter_post
- send email / send outreach / post on X
- can you message / can you reach out
- trust state / trust ladder / promote trust

## Procedure

1. Check trust state for active company (`company_report` headline or `[COMPANY] trust=` in snapshot).
2. **If `learning`**: live tool refuses. Call the draft equivalent:
   - `email_send`/`email_reply` → `email_draft(to, subject, body)`
   - `prospect_outreach` → `outreach_draft(prospect_id, body, channel)`
   - `twitter_post` → `post_draft(content)`
   
   Drafts land at `companies/<slug>/drafts/<kind>/pending/`. Voice contract lints body before persist (see [[voice-extraction-workflow]] if lint fails). Tell operator what you drafted.

3. **If `trial`**: live tools work but each gates MODERATE. Be deliberate — operator just promoted you. Produce ONE quality send, not a batch.
4. **If `operating`**: full autonomy within budget. Voice contract still lints.

## When a live tool refuses

Error message names the replacement and operator action. Example:
```
email_send blocked: company 'acme' in trust state 'learning' — use email_draft.
Operator command: elophanto company trust acme trial.
```
- Don't retry the live tool (gate is operator-decided, not transient).
- Call the named draft tool.
- Tell operator what you drafted + remind them of the promotion command.

## Promotion (operator only)

- **Never call `company_trust_set` yourself.** Operator decides via CLI or via the tool with explicit MODERATE approval.
- Surface readiness signals: voice.yaml exists, 3-5 approved drafts visible, no recent rejections, active strategy.
- After operator promotes to `operating`: live sends become autonomous. Demote with `elophanto company trust <slug> trial` if it goes sideways.

## Hard rules

- ❌ Never `company_trust_set` to promote yourself.
- ❌ Never re-call a live tool after trust-gate refusal.
- ❌ Never batch-draft 10 "in case" messages — produce 1-3 quality samples per channel.
- ❌ Never silently swap channels when one refuses.

## Verify

- [ ] Trust state checked before any live outbound call
- [ ] On gate refusal: draft tool called, not retried
- [ ] On promotion request: I did NOT call `company_trust_set`
