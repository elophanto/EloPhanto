# 90 — Review: the browser must lead, the code must only keep the rules

*Status: review 2026-09-02, requested by Petr after the login script
navigated to a guessed `/login` (a 404) on Brand F while the real Login
button was on screen: "it's a general purpose agent so it shouldn't be
hardcoded." Go-ahead given the same day ("ensure it's the best possible
outcome, this is enterprise now"); steps 1–2 of the build order below are
built and tested, step 3 partly (consent stays a hint), step 4 is the live
run — see "What shipped" at the end.*

## What v2026.06.20 did

At the June release there was no `watch_login` and no scripted site flow.
Sites were driven by the **general-purpose agent** with the browser tools
and the `browser-automation` playbook:

* the agent looks at the page (`browser_get_elements` with indices,
  `browser_read_semantic`, `browser_screenshot` with labelled elements),
  decides what to click, clicks it, and **observes again before the next
  action** — the evidence-gating rule, enforced in code by
  `core/browser_executor.py` (`BrowserExecutionState`: every state-changing
  tool must be followed by an observation; the same failing action three
  times is stagnation and stops the run);
* a login was "click the Log In control you see, fill the fields you see,
  submit, look at the result" — no vocabulary, no URL, no platform
  assumptions; the model perceived each site as it was;
* the outcome was checked by `Agent._verify_browser_task`: a screenshot and
  a separate model call answering "is this done?".

That is why it worked across brands: nothing in it knew the word "Login".

## What was built since (2026-08-26 → 2026-09-02) and where it broke

`core/watch_login.py` (791 lines) and the signed-in half of
`core/watch_catalog.py` re-implement a narrow slice of the above as a
**script with hardcoded vocabularies**:

| constant | what it hardcodes | what it cost |
|---|---|---|
| `LOGIN_ENTRY` | the six spellings of "Log In" | matched a hidden template's "Log In" on Brand F; the visible button was "Login" top right |
| `SWITCH_TO_LOGIN` | "already got an account" wording | clicked switches on pages that had no sign-up panel |
| `/login` fallback (removed today) | an invented address | a 404, filed as the evidence screenshot |
| `SUBMIT_LABELS`, `_SUBMIT_JS` | how a submit button is worded and placed | Brand J/Brand M/Brand K/Brand N "submitted" and stayed logged out — we do not know what the click hit |
| `LOGGED_IN_STRONG/WEAK`, `LOGGED_OUT_WORDS`, `_BALANCE_RE` | what a session looks like in words | "sweeps coins" made a logged-out page a session; then a live session was "no form" because the text came from `<main>` only |
| `LOGIN_ERROR_PHRASES` | how a rejection is worded | any other wording is "logged_out", indistinguishable from a missed click |
| `_CONSENT_LABELS` | how a cookie banner is worded | Brand G's "I Accept" sat in front of the Log In button all day |
| `_SIGNED_IN_NAV` | that the store is behind "Get Coins", the studios behind "Providers" | untested on any site yet; the same class of guess |
| `_PAGE_PATTERNS`, `_INTERESTING` | which URLs hold which catalog | a `/sweepstakes-casinos/reviews/` page was refused as "sweepstakes rules" |
| `KNOWN_REVIEW_URLS`, `_TRUSTED_HOSTS` | one review site's URL scheme | a source the client named — belongs in config, not code |
| `_PROVIDER_ALIASES`, `_FREQ_RULES`, `_CLAIM_RULES` | data normalisation | fine as *fallbacks* behind the model, wrong as the only reader |

Every one of today's fixes (wait for the app to render, count a balance,
re-check after "no form", read the whole page, click visible controls, add
"I Accept") patched one hardcoded assumption with another. The script is
now better at the six sites it has seen and no better at the seventh. The
August sweep that produced the three live sessions (Brand A, Brand D,
Brand C) was this same script; it went 3 for 15.

## What must stay in code

The script also carries things that are **policy**, not perception, and
those are right where they are:

1. **Secrets never enter the model's context.** The vault holds the
   credentials; the code types them. (The June agent could only log in
   when the password was in its prompt — that is worse, not better.)
2. **Never twice in a row.** One attempt per brand per 12 hours, stored
   and merged; repeated failures are how accounts lock.
3. **Never solve a puzzle.** A captcha is reported, a human clears it
   once in the agent's own Chrome.
4. **A verdict needs printed proof.** Whatever judges the page — script
   or model — must quote what it saw; the excerpt is stored with the
   verdict; the screenshot is filed.
5. **The exit is proven before a geo-bound sign-in**, and every row is
   stamped with the session and the exit it was read through.
6. **Nothing is accepted on the player's behalf** (a Terms modal is read
   through, never agreed to).

## Proposed design: the agent drives, the code keeps the rules

`watch_login` and the signed-in catalog read become **thin policy wrappers
around the agent's own browser competence**, using the delegation tier
that already exists (`Agent.run_isolated`, wired to any tool that declares
`_agent` — the same path `delegate` uses):

```
watch_login(brand)
  ├─ policy (code): cooldown check · vault lookup · exit switch + proof
  ├─ perception + action (agent, run_isolated, browser tools + playbook):
  │     goal: "You are on <url>. Get to the point where the site's sign-in
  │            form is on screen, the way a person would (find the control
  │            you can see; if a sign-up panel opens, find its 'already
  │            have an account' switch; clear any cookie banner). Do not
  │            type credentials. Stop and report when: the form is on
  │            screen · the page already shows a signed-in account (say
  │            what proves it) · a captcha or puzzle appears · nothing you
  │            can see leads to a form. Never navigate to an address you
  │            invented."
  ├─ secret step (code): type username/password into the fields the agent
  │     left on screen (the existing fill_and_submit, minus the guessing),
  │     click the form's own submit
  ├─ verdict (agent, one call, page text + screenshot): logged_in /
  │     rejected(<site's words>) / challenge / no_form — with proof quoted
  │     from the page (judge_session already does this; it becomes the
  │     only judge, the word lists become its hints, not its gate)
  └─ record (code): screenshot · excerpt · merge into results.json

watch_catalog_collect customer_state=registered
  ├─ policy (code): session must be live (verdict above), exit stamped
  ├─ agent, run_isolated: "Open the lobby; then, one at a time, the pages
  │     a player reaches for the game providers, the coin store, the
  │     promotions and the loyalty/VIP club — by clicking what you see —
  │     and after each page call browser_get_html so it is on record.
  │     Scroll so lazy-loaded grids are complete."
  └─ extraction (code + model, unchanged): rank the pages the agent read,
        extract per kind, verify every item against the page, stamp rows
```

The hardcoded lists survive only as **hints in the goal text** ("stores
are usually behind Get Coins / Buy / Store") and as **fallback readers**
behind the model (`parse_coins`, `parse_frequency`, the provider aliases).
Control flow never depends on them. `KNOWN_REVIEW_URLS` moves to config
(`watch.research_sources`).

What the agent already provides for free in that loop: evidence gating
(observe after every action), stagnation detection, the labelled
screenshot, `browser_get_elements` by index, shadow-DOM-aware clicking,
and `_verify_browser_task`.

## Build order (each step green, each step keeps the pack unchanged)

1. `core/watch_login.py`: replace `open_login_form` (the click/switch
   script) with `agent_opens_form(agent, url)` via `run_isolated` with the
   goal above and the browser tools only; keep `fill_and_submit` for the
   secret step; make `judge_session` the sole verdict with the word lists
   demoted to hints; delete `LOGIN_ENTRY`, `SWITCH_TO_LOGIN`,
   `_VISIBLE_LOGIN_JS`. Tests: a fake agent that returns the subagent's
   report; no `browser_navigate` in the wrapper; secrets never in the goal.
2. `core/watch_catalog.py`: replace `read_signed_in_pages`' label loop
   with `agent_reads_lobby(agent, url, kinds)`; keep the DOM capture and
   the extraction. Tests: the pages the agent read are ranked and
   extracted; nothing accepted.
3. Move `KNOWN_REVIEW_URLS` to config; `_CONSENT_LABELS` becomes a hint
   (the agent clears banners itself; the deterministic dismissal stays as
   the cheap first try for screenshot capture only).
4. Docs 88 §F and 89 rewritten to match; a live run on the four brands
   the script failed today (Brand E, Brand F, Brand I, Brand G).

Cost: one subagent run per brand per sign-in (a handful of model calls
with screenshots), which is what the June agent spent anyway.

## Asking for

A go-ahead on the design above before any of it is written, or a
different cut of the policy/perception line.

## What shipped (2026-09-02)

* `core/watch_login.py` — `agent_opens_form(agent, url)`: `Agent.run_isolated`
  with `AGENT_BROWSER_TOOLS` only (look, click, scroll, wait, read; no
  `browser_navigate`, no `browser_eval`, no typing, no cookies, nothing
  outside the browser), a 240 s timeout, the `OPEN_FORM_GOAL` playbook
  (observe → act → observe; click the visible control; the sign-up panel's
  switch; never an address) and a two-line report `STATE:` / `PROOF:`.
  `login_to_site(..., agent=)`: the agent gets the form on screen; the code
  types the credentials it never showed the agent; the scorer clicks the
  form's own button and, if the form is still there, `agent_submits_form`
  asks the agent to click it (no secrets involved); the verdict is the
  model's `judge_session` with quoted proof — `logged_in` / `rejected`
  (the site's own words) / `challenge` / `logged_out` — with the keyword
  check as the fallback, and the excerpt stored. The script
  (`open_login_form`) survives only as the path when no agent is wired in.
* `core/watch_catalog.py` — `agent_reads_lobby(agent, bm, url, kinds)`:
  the agent visits lobby, providers, store, promotions and VIP by clicking
  what it sees, scrolls each, and calls `browser_get_html` once per page;
  `_PageRecorder` keeps every capture with its URL; the report's `PAGE n:`
  lines file each capture by kind. `read_signed_in_pages(agent=)` uses it;
  the label loop remains the no-agent fallback.
* `core/task_resources.py` — a run scope opened inside another (a
  subagent inside a tool call) inherits the parent's session-lazy holds;
  BROWSER has capacity one, so this is what keeps a delegation from
  waiting on itself.
* `tools/watch/tools.py` — every watch tool carries `_agent` (injected by
  the Agent like `_router`); `watch_login` and the collector pass it.
* `scripts/watch_live_check.py` — the live run outside the chat: the same
  Agent, tools and vault; `--brand` repeatable, `--read` for the registered
  read of every live session.

## Live results (2026-09-02, `scripts/watch_live_check.py`, chat closed)

Sign-ins, agent-driven: **Brand E, Brand F and Brand G signed in** by
the agent finding the form (4, 4 and 11 actions) and the code typing the
credentials — the three brands the script never managed. Brand A, Hello
Millions and Brand C recognised as live sessions with proof quoted
from the page. **Brand I**: credentials accepted, the site e-mailed a
verification code (new browser) — `verification_required`. **Brand G**
later `rejected` ("Error. Please try another email/username or
password") after three sign-ins in one morning: the cooldown is not to
be overridden for it again.

Signed-in reads (rows stamped `registered`, verified against the page):

| brand | games | coin packages | providers | promotions | loyalty tiers |
|---|---|---|---|---|---|
| Brand A | 63 | 0 | 25 | 11 | 2 |
| Brand E | 56 | 8 | 53 | 7 | 0 |
| Brand D | 59 | 9 | 32 | 6 | 1 |
| Brand F | 60 | 7 | 34 | 11 | 0 |

The register went from 1,658 to 2,002 rows. Each pass found a defect the
previous one hid, all fixed the same day: the recorder kept the agent's
short HTML ask (now captures the full DOM itself); the agent's report was
read only in one format (now loosely, and an unnamed capture is tried for
every kind); the extractor read the first 22,000 characters of a page
whose store modal sat at the end (now the window densest in the kind's
marks); a lobby asked for before it rendered was a shell (now recaptured);
image tiles carried their names in `alt` (now kept); a single-page app's
one URL named everything "game" (now left open); the agent's submit step
was cut off by the injection filter (now Enter is the last resort); forty
actions were not enough for five pages (now sixty, with a report-by note).

Known gaps, by evidence on disk (`workspace/watch/captures/`): **Crown
Coins**' lobby has no game titles in its DOM at all (every tile's alt is
"provider logo"), so its public-research data stands; **Brand A**' store at
/store renders as a near-empty shell within the capture window. Card
Crush, Brand M, Brand K and Brand N still need their passwords checked by
hand; Brand J is rejected from the Texas exit; Brand L was unreachable twice;
Brand B shows a captcha.
