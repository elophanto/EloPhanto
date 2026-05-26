---
name: voice-extraction-workflow
description: Produce a voice contract from operator-curated exemplars (Phase 10). Triggered by exemplar paths, voice intent, or draft lint failure.
license: MIT
metadata:
  author: petr-royce
  version: "1.1.0"
  phase: 10
---

# Voice extraction workflow

## Triggers

- voice extract / voice contract / voice yaml
- learn my voice / mimic this voice / write like
- exemplars / reference posts
- voice_proposed / voice approve
- voice lint failed

## Procedure: extract a voice contract

1. **Check exemplars.** `file_list data/companies/<slug>/exemplars/` recursive. Expect `twitter/`, `email/`, etc. with 2+ `.md` files per channel. If empty: tell operator the path, don't scrape.
2. **`voice_extract(company_id=<slug>, channel=<optional>)`**. Requires ≥2 exemplars per channel scanned. Writes `voice_proposed.yaml`.
3. **Show to operator**: `elophanto voice proposed <slug>` (or file_read). Surface persona / tone / banned phrases / hooks / length bounds.
4. **Operator promotes**:
   - Approve → `elophanto voice approve <slug>` (backs up existing voice.yaml, promotes proposal).
   - Reject → `elophanto voice reject <slug> "<reason>"` archives with reason; next extract reads it.
5. Future drafts auto-lint against the contract.

## When a draft lint fails

ToolResult error names violations (e.g. `voice lint failed: banned phrase 'leverage'; too long: 312 chars (max 240)`).

- **Default**: revise the body honoring the constraints. LLM does this naturally on next planning cycle.
- **Rare**: contract is outdated. Tell operator + ask for new exemplars.
- Never bypass via live tool to skip the draft gate.

## When no voice.yaml exists

Lint is fail-soft (passes everything). Day-0 state. Tell operator the contract is empty + point at `exemplars/` path. While missing, default to [[b2c-marketing-voice]] principles (no "leverage", concrete object up front, etc.).

## Hard rules

- ❌ Never promote `voice_proposed.yaml` → `voice.yaml` yourself. Operator only.
- ❌ Never scrape URLs for exemplars — operator pastes deliberately.
- ❌ Never write `voice.yaml` directly via file_write.
- ❌ Never lint a draft against the wrong company's voice — set the contextvar first.

## Verify

- [ ] ≥2 exemplars per channel before `voice_extract`
- [ ] `voice_proposed.yaml` written (not `voice.yaml`)
- [ ] On lint failure: body revised, not live tool called
