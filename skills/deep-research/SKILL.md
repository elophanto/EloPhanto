---
name: deep-research
description: Use when investigating any claim, question, or topic where the easy first answer is likely insufficient. Frames the question as a falsifiable claim, tiers sources, steel-mans the strongest dissent, and cross-validates via independent paths before stating a confidence. Replaces "I'll do a quick web search" with structured investigation.
---

## Triggers

- deep research
- research this
- investigate this
- get to the bottom of
- is this true
- fact-check
- validate this claim
- what's actually going on
- separate signal from noise
- find the contrarian view
- steel-man this
- is this consensus right
- mainstream view vs reality
- dig deeper
- not satisfied with surface answer

# Deep Research

## Overview

Most "research" via web search returns the *same answer five times* because
five sites copy from one source. That isn't research, it's consensus
amplification. This skill exists to do the harder thing: frame the question
properly, tier the evidence, steel-man the strongest dissent, and arrive at
a confidence interval — not a confident-sounding paragraph.

**Iron rule:** never state a conclusion without (a) the source tier,
(b) the strongest counter-argument and what would refute it, and (c) what
you don't know.

## Phase 1 — frame as a falsifiable claim

Restate the open question as one or more claims that *could be wrong*. Not
"is X effective?" but "the claim that X reduces Y by ≥Z% in population P".

Vague questions get vague answers. The first thing to do is sharpen.

If the user's question can't be turned into a falsifiable claim, that's
itself the finding — surface it ("this question is unfalsifiable as posed
because…") instead of pretending to research it.

## Phase 2 — set the budget

Before searching anything, write down:

- **Source budget**: ~6–10 sources for routine, ~20+ for high-stakes.
- **Turn budget**: how many `web_search` / `web_extract` calls maximum.
- **Stop conditions**:
  - confidence reached and stable across two independent source paths, OR
  - budget exhausted (write up the partial answer + remaining unknowns), OR
  - claim is unfalsifiable / no primary sources exist (say so).

Bounded budgets prevent runaway investigation. Budget exhaustion is a valid
outcome — *acknowledge what you couldn't verify* rather than padding with
weak sources.

## Phase 3 — tiered source rubric

Score every source by tier *before* incorporating it into the answer.

| Tier | What | Examples |
|---|---|---|
| **1. Primary** | Original data, the actual document | Papers (with methods), court filings, SEC 13F/insider, on-chain transactions, datasets, official statements, GitHub commits, regulator filings |
| **2. Expert** | Domain experts citing primary | Survey papers, industry analyst reports, peer-reviewed reviews, named expert blogs with primary citations |
| **3. Journalism** | Reporters synthesising | Quality outlets with named reporters, sourced quotes, links to primary |
| **4. Aggregator/social** | Re-summarising | Reddit/HN/X consensus, Wikipedia (use as map, not territory), generalist news rewrites |
| **5. AI/SEO** | Pattern-matching content | LLM-generated articles, content farms, "10 things you need to know" listicles |

**Hard rules:**

- A claim that exists *only* at tier 4–5 is unverified. Mark it as such.
  Don't escalate it just because many sites repeat it (citation laundering).
- When tier 3 cites tier 1, go read tier 1. Don't trust the summary.
- A single tier-1 source beats ten tier-4 sources saying the same thing.
- Tier-5 sources are noise unless they happen to *quote* a tier-1 source —
  in which case they're a pointer to tier 1, not a source themselves.

Use `web_search` (Search.sh) and `web_extract` to pull content; for
high-stakes investigations also pull from `knowledge_search(scope="learned")`
in case we already have prior lessons that touch this.

## Phase 4 — consensus vs dissent

For each major claim, identify two camps:

1. **Mainstream consensus** — what most tier-2/3 sources say.
2. **Strongest dissent** — the most credentialed, best-evidenced voice
   disagreeing with consensus. Not a random contrarian. The one whose
   argument would actually shift consensus if it stood up.

**Steel-man the dissent.** Write the dissenting argument in its
strongest form — what you'd say if you genuinely had to defend it.
Then ask: *what evidence would refute it?* If that evidence exists and
holds, the dissent loses. If the steel-manned dissent stands up to its
own falsification test, the consensus is weaker than it looks.

This step is non-optional. If you can't find a credible dissent, that
*is* the finding — say "no credible dissent exists in tiers 1–2,
which suggests strong consensus *or* under-investigation by experts;
flag for follow-up."

## Phase 5 — cross-validation via independent paths

A claim corroborated by two sources from the *same* domain is barely
stronger than one source. A claim corroborated by sources from
*independent* domains (e.g., on-chain data + a court filing + a
named expert) is much stronger.

For the central claim, identify ≥2 independent paths to the same
conclusion. If you can only find one path, your confidence stays
bounded by that single path's tier.

## Phase 6 — log every step

Keep a per-investigation research log so the work is reproducible
and the agent's reasoning chain is greppable. Use either:

**Option A** (markdown — preferred for narrative investigations):
write to `knowledge/learned/research/{date}-{slug}.md` with frontmatter:

```markdown
---
claim: "<falsifiable claim>"
verdict: supported | contradicted | inconclusive
confidence: 0.0–1.0
sources: <count>
tiers: {primary: N, expert: N, journalism: N, aggregator: N, ai: N}
dissent: <one-line steel-man of strongest dissent>
unknowns: <list of what wasn't verified>
---

(narrative: framing → sources walked → dissent → cross-validation →
verdict + confidence + caveats)
```

**Option B** (TSV — preferred for parametric / multi-claim sweeps):
append to `knowledge/learned/research/{slug}.tsv`:

```
claim	source_url	tier	supports	confidence	notes
```

Use `knowledge_write` to persist; the indexer makes future
`knowledge_search` queries surface prior investigations on the same
claim. Don't re-research what you already investigated last week —
check the log first.

## Phase 7 — output

The deliverable is *not* a paragraph. It's:

1. **Verdict** (one sentence) — supported / contradicted / inconclusive.
2. **Confidence** (0.0–1.0) — what would shift it up or down.
3. **Strongest evidence** — the single best citation, with its tier.
4. **Strongest counter** — the steel-manned dissent + why it lost (or didn't).
5. **What you don't know** — the bounded unknowns. Always non-empty.
6. **Reproduction trail** — link to the research log file.

Then, if the user asked a question (vs. asking you to investigate), a
2–4 sentence direct answer that respects all the above.

## Hard rules — what NOT to do

- **No "I read X sources and they all agree"** without naming the tiers.
  Five tier-4 sources agreeing is noise, not signal.
- **No conclusion without a steel-manned dissent** — even if you reject
  it, do the work of stating it.
- **No undisclosed primary→summary chains.** If you read a summary that
  cites a primary, go read the primary. If you can't access it, say so.
- **No certainty leaks.** If your evidence is mostly tier 3, the verdict
  is "supported by journalism, not yet by primary." Don't round up.
- **No infinite digging.** When the budget hits, *stop and report*, even
  partial. Resuming with more budget is a separate investigation.
- **No pattern-matching to past cases** without checking they apply.
  "This looks like the X situation" is a hypothesis, not a finding.

## When to escalate vs continue autonomously

This skill is designed for the **autonomous mind** and **heartbeat**
contexts — it does not pause to ask the user "should I keep going?".
The loop runs until the budget is hit or stop conditions are met,
exactly like the autonomous-experiment loop.

Escalate to the user only when:

- The claim is unfalsifiable as posed (ask for sharper question).
- All primary sources are paywalled / inaccessible (ask for access).
- The strongest dissent is *credible enough that the verdict could
  flip with more investigation* — surface it as a "taste" decision.
- Budget exhausted and confidence still <0.6 on a high-stakes claim.

Otherwise, finish the investigation, log it, return the verdict.

## What this skill does NOT do

- Replace expert judgment in domains the agent isn't trained for
  (medical, legal, financial advice — the tier-1 source is "ask a
  professional," and the verdict on synthesised opinion is "do not act
  on this without one").
- Auto-publish findings. The output is a research log + structured
  verdict; *acting* on the verdict is a separate decision the user
  takes.
- Investigate live trading signals or short-horizon market movement
  (different skill; this one is for claims that are testable on a
  longer time horizon than they're tradable).

## Verify

- Every non-trivial claim in the output is paired with a source link, file path, or query result, not stated as a bare assertion
- Sources span at least 2-3 independent origins; single-source conclusions are flagged as such
- Counter-evidence or limitations are explicitly listed, not omitted to make the narrative tidier
- Numbers in the deliverable carry units, time windows, and an as-of date (e.g., '$1.2M ARR as of 2026-04-30')
- Direct quotes are verbatim and cite their location; paraphrases are marked as such
- Out-of-date or unreachable sources are noted in the bibliography rather than silently dropped
