---
name: voice-extraction-workflow
description: How to produce a voice contract for a company from operator-curated exemplars (Phase 10). Triggered when the operator drops reference posts/emails, asks about voice style, or when a draft lint fails because voice is misconfigured. Pairs with the b2c-marketing-voice skill (principles) — this one is the procedure.
license: MIT
metadata:
  author: petr-royce
  version: "1.0.0"
  phase: 10
---

# Voice extraction workflow

When the operator wants the agent to write in a specific voice (mirroring real posts/emails from accounts they admire), this is the procedure. It produces the `voice.yaml` contract that lints every future draft for that company.

## Triggers

- voice extract
- voice contract
- voice profile
- voice yaml
- read my style
- learn my voice
- learn this style
- mimic this voice
- write like
- match the tone
- exemplars
- reference posts
- voice_proposed
- elophanto voice
- voice approve
- voice lint failed

## When this skill fires

- Operator drops exemplar markdown files at `data/companies/<slug>/exemplars/<channel>/*.md`
- Operator asks "learn to write like X" or hands you specific accounts to mimic
- A draft tool fails with `voice lint failed: …` and you need to revise OR the contract itself is wrong
- Operator asks about voice contract for a company

## Procedure: extract a voice contract

1. **Check the exemplar directory.** `file_list data/companies/<slug>/exemplars/` (recursive). Expect channel subdirs like `twitter/`, `email/`, `linkedin/`. Each subdir has 2+ `.md` files (one post/email per file). If empty, tell the operator the path and ask them to drop files; do NOT scrape websites yourself (the operator pastes deliberately).

2. **Run extraction.** `voice_extract(company_id=<slug>, channel=<optional>)`:
   - Without `channel`, all channel subdirs are read and merged
   - With `channel`, only that subdir is used
   - Tool requires ≥2 exemplar files (otherwise the extraction is noise)
   - Writes `data/companies/<slug>/voice_proposed.yaml` — the LLM-distilled draft contract

3. **Show the proposal to the operator.** `elophanto voice proposed <slug>` (or `file_read data/companies/<slug>/voice_proposed.yaml`). Surface the persona, tone, banned phrases, allowed hooks, length bounds.

4. **Operator approves OR rejects:**
   - **Approve:** `elophanto voice approve <slug>` (or operator manually renames). Backs up any existing `voice.yaml` to `.bak.<timestamp>`, promotes the proposal to active. From this point every draft for the company gets lint-gated.
   - **Reject with reason:** `elophanto voice reject <slug> "<reason>"` archives the proposal under `voice_rejected/voice_proposed.<timestamp>.yaml` with the reason embedded. Next `voice_extract` call should read this rejection context and revise.

5. **Done.** Future `email_draft` / `outreach_draft` / `post_draft` calls auto-lint against the new contract. Lint failures return `ToolResult(success=False, error="voice lint failed: …")` — the LLM revises naturally on the next planning cycle.

## Procedure: when a draft lint fails

1. **Read the failure.** The ToolResult error names the violations (e.g. `voice lint failed: banned phrase 'leverage'; too long: 312 chars (max 240); opening line matches no allowed hook template`).
2. **Decide: revise body OR revise contract?**
   - **Revise body** (default): the contract is right, your draft drifted. Rewrite the body honoring the constraints and call the draft tool again. The LLM does this naturally if it sees the violations.
   - **Revise contract** (rare): the operator told you to write a specific way and the active `voice.yaml` is wrong. Run `voice_extract` again with new exemplars OR tell the operator the contract is outdated and ask for new exemplars.
3. **Never bypass the lint.** Don't try to send via a live tool to skip the draft gate — the lint applies to drafts because that's where it catches slop before it reaches the operator's queue. Live tools have their own gates.

## Procedure: voice contract is missing (fail-soft)

If `voice.yaml` doesn't exist for a company, the lint passes everything. This is the day-0 state — the operator hasn't curated exemplars yet.

1. Tell the operator the voice contract is empty: `elophanto voice list` shows `not configured`.
2. Point them at the exemplars path: `data/companies/<slug>/exemplars/twitter/` etc. The README the `company_onboard` tool seeded explains the flow.
3. While missing, you can still draft — but your defaults must honor the [[b2c-marketing-voice]] principles (no "leverage", no "We help businesses", concrete object up front, etc.).

## What NOT to do

- ❌ Do NOT promote `voice_proposed.yaml` → `voice.yaml` yourself. Operator decides.
- ❌ Do NOT scrape exemplar content from URLs. The operator pastes deliberately into `exemplars/<channel>/*.md`. Scraping breaks the trust model.
- ❌ Do NOT skip `voice_extract` and write `voice.yaml` directly via `file_write`. The extraction step + proposal review is the operator's audit point.
- ❌ Do NOT lint a draft against the wrong company's voice — the lint reads the active company's `voice.yaml`. If you're drafting for `acme-inc`, set the contextvar first.

## Verify

- [ ] Exemplar directory has ≥2 files per channel before calling `voice_extract`.
- [ ] `voice_proposed.yaml` was written, not `voice.yaml` (only operator promotes).
- [ ] On lint failure: the body was revised, NOT a live tool called.
- [ ] If contract was the problem: new exemplars dropped, new extraction run.

Emit `Verification: PASS / FAIL / UNKNOWN` per check.
