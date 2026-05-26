---
name: trust-ladder-workflow
description: How to behave per company trust state (learning / trial / operating). When a live outreach tool refuses, this skill names the canonical draft replacement and the operator-facing path to promotion. Auto-loaded on any outbound-channel tool name.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 9
---

# Trust ladder workflow — DO NOT spam

Every ABE company has a three-state trust ladder controlling whether live outbound communication (email, X posts, prospect outreach) is allowed:

| State | Live outreach? | Operator approval per call? | Default for |
|---|---|---|---|
| `learning` | **REFUSED** — draft only | n/a | new companies |
| `trial` | allowed | MODERATE permission per call | operator-promoted after voice approval |
| `operating` | allowed | only within budget + permission_mode | mature companies |

## Triggers

- email_send
- email_reply
- prospect_outreach
- twitter_post
- send email
- send outreach
- post on X
- post to twitter
- publish post
- can you email
- can you post
- can you message
- can you reach out
- trust state
- trust ladder
- promote trust
- elophanto company trust

## When this skill fires

Before calling any live-outreach tool, OR when the operator asks about the trust ladder / promotion / a refused send.

## Procedure: when you want to send something outbound

1. **Check the trust state** for the active company. `company_report <slug>` shows it in the headline. The `[COMPANY]` block in the state snapshot also shows `trust=<state>`.

2. **If `trust=learning`:** the live tool will refuse. Call the draft equivalent instead:
   - `email_send` / `email_reply` → `email_draft(to, subject, body)`
   - `prospect_outreach` → `outreach_draft(prospect_id, body, channel)`
   - `twitter_post` → `post_draft(content)`
   
   Drafts land at `companies/<slug>/drafts/<kind>/pending/<id>.md` as operator-readable Markdown. The voice contract (Phase 10) lints every draft before persistence — see [[voice-extraction-workflow]] if lint fails. Tell the operator what you drafted; they review via `elophanto drafts list`.

3. **If `trust=trial`:** live tools work, but each call gates through MODERATE permission. Be especially careful — operator just promoted you out of `learning`; this is the proof-of-trust phase. Produce ONE high-quality send, not a batch.

4. **If `trust=operating`:** full autonomy within budget + permission_mode. Send live; don't ask per call. But the voice contract still lints — slop drafts still fail, just with no "draft and wait" fallback.

## Procedure: when a live tool refuses

The error message names the canonical replacement and the operator action. Example:

```
email_send blocked: company 'acme-inc' is in trust state 'learning' which forbids
live outreach until the operator approves your voice + samples and promotes the
company to 'trial' or 'operating'. Use email_draft instead — it writes the draft
to companies/acme-inc/drafts/ for operator review. Operator command:
elophanto company trust acme-inc trial.
```

1. **Do not retry the live tool** — the gate is operator-decided, not transient.
2. **Call the named replacement** (`email_draft` in the example).
3. **Tell the operator** what you drafted and remind them of the trust command if they want to enable live sends.

## Procedure: when operator asks to promote

1. **Do NOT promote trust yourself.** Even if you're sure the voice is good and the samples are clean. Operator-only via:
   - `elophanto company trust <slug> <state>` (CLI)
   - `company_trust_set(slug, state, reason)` tool — MODERATE, operator approves per call
2. **Surface what the operator should check before promoting:**
   - `voice.yaml` exists and reflects approved exemplars
   - 3-5 approved drafts (`drafts/<kind>/approved/`) showing the voice
   - No rejected drafts in the last 7 days (or rejections were minor)
   - Strategy is in active state (`strategy/active/strategy.yaml`)
3. **If operator promotes:** acknowledge + remind them that going to `operating` means autonomous live sends. They can demote with `elophanto company trust <slug> trial` or `learning` if it goes sideways.

## What NOT to do

- ❌ Do NOT call `company_trust_set` to promote yourself.
- ❌ Do NOT re-call the live tool after a trust-gate refusal.
- ❌ Do NOT batch-draft 10 messages "in case" — produce 1-3 high-quality drafts per channel and present them.
- ❌ Do NOT bypass voice lint by going straight to live tools — the lint runs on drafts; if voice fails, the live tool would have failed quality anyway.
- ❌ Do NOT silently swap to a different channel when one channel's trust state refuses. Tell the operator.

## Verify

- [ ] Before calling any live outbound tool, the trust state was checked (state snapshot or `company_report`).
- [ ] On gate refusal: the draft tool was called, NOT the same live tool retried.
- [ ] On chat about promotion: I did NOT call `company_trust_set`.
- [ ] Drafts I produce reference the prospect/email/post they're for, not generic placeholders.

Emit `Verification: PASS / FAIL / UNKNOWN` per check.
