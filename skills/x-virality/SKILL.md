---
name: x-virality
description: Concrete, algorithm-grounded guidance for writing X posts that the For You feed ranks high. Distilled from the public source of X's ranking system (github.com/xai-org/x-algorithm, May 2026 release). Use this BEFORE drafting any X post or reply. Pairs with the `x_style_preflight` tool (mechanical banned-phrase check) and the `twitter-marketing` skill (general practice).
---

## Triggers

- x post
- twitter post
- twitter reply
- x reply
- x engagement
- web3 reply
- x growth
- viral
- engagement bait detection
- post quality

## Why this exists

The X For You feed is ranked by a Grok-based transformer (`Phoenix`) that predicts **probabilities for 22 distinct user actions** on every post and then computes a weighted sum. The weights are tuned at runtime via A/B testing — they aren't in the open source release — but **the list of signals that matter is public**, and so are the filters that remove content before scoring even starts.

This skill maps every signal to concrete writing choices the agent can make. Treat it as a reference, not a checklist — but the patterns are mechanically real, not vibes.

Source: https://github.com/xai-org/x-algorithm (Apache 2.0).

## How the algorithm scores

```
final_score = Σ (weight_i × P(action_i))
```

There is **no** "engagement score" the model optimizes. There are 17 positive-weighted action probabilities and 5 negative-weighted ones. A post that gets a quick like and a scroll-past is mediocre; a post that holds attention, generates replies, and earns follows is gold. The model penalizes content that gets ignored as hard as content that gets reported.

## Positive signals — what to design for

| Signal | What it means | How to earn it |
|---|---|---|
| **`dwell`** + `cont_dwell_time` | Time spent reading the post in feed (continuous, not just a flicker) | **Most under-appreciated signal.** Write content that *holds attention*. A 2-line punchline gets a like-and-scroll; a 3-4 sentence concrete read holds the eye. Open with the hook; the second line keeps them reading. |
| `favorite` | Like | Concrete, specific, sometimes funny, current. Avoid generic. |
| `reply` | Reply | Provoke replies on purpose: take a side, mild contradiction, ask a *real* question (not "what do you think"). Replies are independently weighted; a post with 5 replies > a post with 50 likes and 0 replies. |
| `retweet` | Repost | Quotable single-idea posts. The idea is portable: someone reposts it as a stand-alone unit. |
| `quote` + `quoted_click` | Quote tweet + click on the quoted | High signal because the user did EXTRA work to add their own framing. Posts that invite quote-tweeting are direct claims people want to react to. |
| `share` + `share_via_dm` + `share_via_copy_link` | Sharing | Posts that get DM'd or copy-linked to someone are usually *informational* ("look at this") or *funny enough to send a friend*. Concrete data > opinion for share_via_dm. |
| `profile_click` | User taps your name/handle | Make the post pose a question about *who is writing this*. Strong claims, distinctive voice, useful info → "who is this account?" → profile_click. Hard signal, weighted high. |
| `follow_author` | New follow earned from this post | The biggest single positive. Posts that earn follows usually do one of: deliver useful info the reader wants more of, take a contrarian-but-defensible position, or show a specific *track* (numbers, on-chain evidence, repeatable work). |
| `click` | Link click (external URL or thread) | Only fires when there's a link/expander. Be selective with links; an irrelevant link drags `not_dwelled`. |
| `photo_expand` | Image tap-to-expand | Use images that *reward expansion*: chart with detail, screenshot with readable text, image worth seeing full-size. Decorative images don't earn this. |
| `vqv` (Video Quality View) | Video watch ≥ min duration (typically 6+ seconds, configurable) | If posting video: front-load the hook in the first 3 seconds. Sub-6s watch time = no signal. |

## Negative signals — what destroys a post

| Signal | What triggers it | Consequence |
|---|---|---|
| **`not_dwelled`** | User scrolled past quickly without reading | **The hidden killer.** Posting empty bait or low-signal one-liners that don't hold attention actively *lowers* your score — worse than not posting at all. |
| `not_interested` | "Show less of this" click | Often triggered by: pump/promo bait, ragebait, generic AI sludge, off-topic for the audience. |
| `block_author` | Block | Aggressive engagement-baiting, doxx-adjacent posts, scammy framing. |
| `mute_author` | Mute | Posting *too frequently* on the same topic; spammy cadence; ratio-baiting. |
| `report` | Report | Obvious bans. Also: token-pump framing, "send me your address," fake giveaways. |

## Hard filters — content REMOVED before scoring

Even a perfect post gets zero reach if any of these fire. The algorithm pre-filters before ranking:

- **`AgeFilter`** — posts older than the threshold are dropped. **Freshness matters.** React fast or skip.
- **`DropDuplicatesFilter`** — same content posted again = dropped. Don't recycle exact phrasing.
- **`RepostDeduplicationFilter`** — multiple reposts of the same source post are deduped.
- **`SelfpostFilter`** — your own posts don't show up in your own feed (irrelevant for posting, but: don't write *for yourself*, write for the audience).
- **`MutedKeywordFilter`** — words muted by individual users. Less actionable but: niche jargon over generic terms when both work.
- **`AuthorSocialgraphFilter`** — blocked/muted authors filtered. Don't earn blocks/mutes.
- **`PreviouslySeenPostsFilter`** + **`PreviouslyServedPostsFilter`** — a user won't see the same post twice. **Implication**: posting two similar takes back-to-back means the second probably won't reach the same audience.
- **`VFFilter`** (post-selection) — spam/violence/gore/deleted. Don't write anything classifier-flaggable.
- **`DedupConversationFilter`** — multiple branches of one conversation tree are deduped. Posting 5 replies on the same thread to different sub-replies → most won't surface.

## Author diversity multiplier

After scoring, posts from the same author for the same viewer have their scores attenuated by a decay factor. **Implication**: bursting 5 posts in 10 minutes means posts 2–5 are heavily down-weighted vs the first. Stagger posts. The active engagement loop schedule (`b3bb7508`) firing at `:25` and the original-post schedule (`7412d4eb`) firing at `:00` already build in 25-minute spacing — preserve that. If running ad-hoc posts, leave at least 20 minutes between them.

## Content classifiers (Grox layer)

The algorithm ALSO runs LLM-based content classifiers on every post before ranking. Specifically:

1. **`BangerInitialScreenClassifier`** — scores `quality_score`, `slop_score`, and a content-category tag set. There is *literally a slop detector*. Posts that read as low-effort / AI-assistant prose / consultant phrasing get a high slop_score and rank lower.

2. **`PostSafetyDeluxeClassifier`** — boolean safety flags. Triggers on policy violations, sensitive content.

3. **`SpamEapiLowFollowerClassifier`** — separate spam check **specifically for low-follower accounts** (we ARE one). Be aware: thresholds are stricter on us than on established accounts. Pump/promo bait, repeated identical structure, link-spam patterns will fire this.

4. **`ReplyRankingClassifier`** — replies get their own ranking model. The reply doesn't have to be a brilliant standalone post; it has to be a *good reply to the parent*. Stay attached to the parent's actual topic.

## Practical rules for our agent

These are the concrete writing rules derived from the above. Apply them in order before posting.

### 1. Open with a hook in the first 3-8 words

The `dwell` signal is gated on the *first impression*. If the first line doesn't earn the eye, the user scrolls and you eat a `not_dwelled` penalty. Hooks that work:

- Concrete number: "btc etf flows finally coughed up a real number: ~$635m out on may 13"
- Counter-claim: "nature is healing"
- Specific contradiction: "wrong layer to blame"
- Question that's actually a question: "show me the bid after the easy part"

Hooks that DON'T work:

- Generic abstract: "thoughts on the future of"
- Reassuring framing: "interesting development today"
- AI-assistant voice: "as an ai, i find this"
- Listicle setup: "5 things to know about"

### 2. Make people stop and read (dwell, not just glance)

Two-line posts get likes but lose on `dwell` and `cont_dwell_time`. A 3-4 sentence concrete read with one actual idea outperforms a clever one-liner unless the one-liner is *unusually* punchy.

Good shape: hook → concrete fact/number → consequence or implication. Three units, total under 280 chars.

```
btc etf flows finally coughed up a real number: ~$635m out on may 13, worst day in months.

price near 80k while funding is still muted is not panic. it looks more like big money taking chips off without retail getting the memo.
```

Three units. Reader's eye lands at the start, gets pulled into the middle (data), exits with the implication. That post earned a `dwell`.

### 3. Provoke replies, don't beg for them

`reply` is weighted independently. Posts that earn replies usually do one of:

- **Take a side**: "privacy before pmf sounds like homework." Defensible but contestable → people argue.
- **Ask a *real* question**: "show me the bid after the easy part" — implies a missing answer, not "what do you think?"
- **Mild contradiction of a popular take**: "leverage is a feature, not a bug, until it isn't" — invites the other side to push back.

Do NOT ask "RT if you agree" — fires not_interested.

### 4. Earn the profile click + follow

These are the heaviest positive weights. The user is choosing to *learn more about the source*. Earn this by:

- Distinctive voice (lowercase CT shape, specific cadence — don't sound like every other crypto account).
- Concrete track record visible in the post itself: numbers from actual work, on-chain evidence, a specific position taken.
- Something they want MORE of: useful info, defensible takes, a specific worldview.

If every post is generic news commentary, profile clicks stay flat. If posts show consistent voice and edge, profile_click + follow_author both fire.

### 5. Never write for `not_dwelled`

The single most-underestimated penalty. Examples of what eats `not_dwelled`:

- Empty hype: "huge week ahead 🚀🚀🚀"
- Generic platitudes: "build > talk"
- Engagement bait: "follow for more alpha"
- Half-thoughts: "interesting if true"

Each of these gets the eye for half a second, fails to hold attention, and *actively lowers* your future score with that user. **Better to not post than to post one of these.**

### 6. Stay fresh — react fast or don't react

`AgeFilter` drops old posts. If you're replying to a thread, do it in the first hour or two. Replying to 8-hour-old threads earns almost zero reach because the post is filtered out of most feeds before scoring.

For originals: connect to *today's* signal (price move, news, just-shipped product) when possible. Evergreen takes are fine but compete against the entire history of evergreen content.

### 7. Avoid the slop detector

The `BangerInitialScreenClassifier` scores `slop_score`. High slop_score = ranked lower. What reads as slop:

- AI-assistant prose ("as an ai", "i can help", "i'd recommend")
- Consultant cadence ("the future of", "is the part that matters", "under the hood")
- Generic praise / customer-support tone
- Listicle setups ("5 reasons why")
- Anything that could appear in a SaaS product critique blog without modification

The `x_style_preflight` tool (call it before every post) catches the explicit phrase list. The slop detector catches the *shape*. Read your draft aloud — if it sounds like a press release or a fintech blog, it's slop. Rewrite.

### 8. Be careful with images and video

`photo_expand` is positive ONLY if the image rewards expanding. Decorative stock images do nothing.

`vqv` requires meeting the minimum video duration (~6s by default). Don't post sub-6s videos — the watch counts as `not_dwelled`, not `vqv`.

If posting a chart or screenshot: make sure it's *readable when expanded* and *carries the post's claim*. Don't post a chart that doesn't directly support the words.

### 9. Don't stack posts on yourself

Author diversity decay attenuates rapid same-author posts. Stagger:

- Reply schedule fires at `:25`, original schedule at `:00` → 25-minute gap built in.
- Ad-hoc posts: at least 20 minutes between, ideally 30+.
- Never burst 3 posts in 10 minutes — posts 2 and 3 will reach near-zero.

### 10. Watch for spam-low-follower triggers

The `SpamEapiLowFollowerClassifier` is stricter on low-follower accounts. We trip it more easily than @verified-bigaccount does. Specifically avoid:

- Repeating the same post structure 5+ times in a day.
- Posts with multiple external links to non-major domains.
- Anything that reads as crypto-token-shill, even if it's our own `$ELO`.
- "Send me a DM" / "follow me" patterns.

## Decision tree before posting

1. Did `x_style_preflight` pass? (mechanical check, banned phrases) → if no, rewrite.
2. Read the draft aloud — does it sound like a person or like a press release? → if press release, rewrite.
3. Does the FIRST LINE earn the eye in 3-8 words? → if no, replace the lead.
4. Is there at least one CONCRETE thing (number, named entity, specific event, sharp claim)? → if no, abandon or rewrite.
5. Could a reasonable person disagree with this? → if no (uncontroversial), it'll earn likes but not replies. Consider sharpening.
6. Would this be embarrassing on the profile in 6 months? → if yes, skip.
7. Did the agent post within the last 20 minutes? → if yes, queue this for later.

If all 7 pass, post. After posting, verify the live URL and record it.

## What this skill does NOT cover

- **Ads / promoted content** — the algorithm handles ads via a separate `home-mixer/ads/` module. We don't promote.
- **DM / messaging engagement** — different surface, different ranking.
- **Twitter Spaces** — handled by a separate component.
- **Community Notes** — separate moderation layer.
- **Reply ranking specifically** — there's a `ReplyRankingClassifier` we don't have access to internals of. Best general guidance: stay attached to the parent's topic, be concrete, don't pivot to your own agenda.

## Quick reference card

**Maximize**: dwell, reply, follow_author, profile_click, share. Hook in first 3-8 words. Take a defensible side. One concrete unit (number / named thing / specific claim). Stagger by 20+ min.

**Avoid**: not_dwelled (empty bait), not_interested (sludge), mute (over-posting), slop_score (consultant cadence + AI-assistant voice). Fresh > generic. CT voice > corporate.

**Always**: run `x_style_preflight` before posting. Verify live URL after.

## Verify

After running this skill, the post must satisfy these mechanical checks:

- [ ] `x_style_preflight` returned `pass=True`
- [ ] First 3-8 words contain a concrete hook
- [ ] At least one specific element: number, named entity, or sharp claim
- [ ] Reads aloud as a person, not a press release
- [ ] Posted at least 20 minutes after the previous post from this account
- [ ] Live URL verified via browser_extract showing the exact text and timestamp
