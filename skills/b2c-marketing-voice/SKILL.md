---
name: b2c-marketing-voice
description: Anti-slop principles for B2C social posts and outreach. Use BEFORE drafting an email, X post, or prospect message so the body reads like a person, not an LLM. Pairs with the Phase 10 voice contract (data/companies/<slug>/voice.yaml) — this skill is the meta-principles; voice.yaml is the per-company specifics. Distilled from public marketing patterns (jackfriks/b2c-marketing on ClawHub) — not a copy.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 10
---

# B2C marketing voice — anti-slop rules

When you're drafting an outbound message (email, prospect outreach, X post, LinkedIn) for a B2C audience, the default LLM voice is the failure mode. Read this skill, then write. Then run `voice_lint` to catch what slipped through.

## Triggers

- email_draft
- outreach_draft
- post_draft
- twitter_post
- write a tweet
- write a post
- cold email
- outreach message
- social media post

## The four dead patterns (do NOT use)

1. **Self-focused hook**. `We help businesses leverage AI to...` / `Our team is excited to...` / `At <Company> we believe...` — reader scrolls past in 0.3s. Open on THEM or on a CONCRETE OBJECT.
2. **Generic CTA**. `DM me`, `check the link in bio`, `book a call`, `learn more` — these are not CTAs, they are noise. Either soft-CTA (`if this resonates...`) or zero-CTA (let the post stand).
3. **Corporate filler**. `leverage`, `unlock`, `synergy`, `in today's fast-paced world`, `are you tired of`, `imagine if`, `let me explain why`. These are LLM tells. Any one of them and the reader knows.
4. **Abstract claim with no object**. `AI is changing everything` / `productivity is the new luxury`. No screenshot, no number, no person — nothing for the reader to anchor on.

## The four winning shapes (use one)

1. **Another person + conflict + showed them + changed mind.**
   `My dad didn't believe agents could ship real code. I showed him the PR diff. Now he asks me daily what they shipped.`

2. **POV: <specific scenario>.**
   `POV: you check your agent's overnight log and find 4 closed tickets you didn't write.`

3. **I used to <wrong belief>. Then <concrete moment>. Now <new belief>.**
   `I used to think prompts were the moat. Then I watched a 12B model out-plan GPT-4 on tool use with the same prompt. Now I think the orchestration is.`

4. **Concrete object up front.**
   A screenshot, a number, a single observed line of code, a single quoted sentence from a user. Then your one-line take. Then stop.

## Length defaults (override per voice.yaml)

- X post: 80-240 chars. If you wrote 280 you padded. Cut.
- Cold email body: 40-80 words. Subject is its own contract — no preamble in body.
- LinkedIn post: 400-800 chars. The hook line stands alone; the rest is one block.

## Before you draft

1. `voice_show` — if `has_voice=True`, the company's voice.yaml is the final authority and overrides anything in this skill.
2. Pick one winning shape from the list above. Name the shape in your reasoning so the operator can audit your choice.
3. Identify the CONCRETE OBJECT or CONCRETE PERSON. If there isn't one, don't draft yet — go find one (call browser_navigate, ask the operator, read a real prospect's bio).

## After you draft

1. `voice_lint(text=<body>)` — fix any violations before calling the draft tool. The draft tool will lint again; catching it here saves a round-trip.
2. Reread the opening line out loud. If it sounds like a press release, rewrite it.
3. Reread the CTA. If it's `DM me` or `check the link`, delete it.

## What this skill does NOT do

- It does NOT replace the per-company voice.yaml. voice.yaml wins on every conflict.
- It does NOT apply to B2B technical writing (changelog, docs, internal memos) — those have different conventions.
- It does NOT produce hooks for you. It tells you which shapes work and which fail; the operator's exemplars (and your judgement) produce the actual line.
