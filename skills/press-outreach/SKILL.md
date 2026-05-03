---
name: press-outreach
description: Journalist press outreach for product launches. Find the right journalist, craft a personalized pitch, manage follow-ups. Based on levelsio's MAKE handbook press strategy.
---

## Triggers

- press outreach
- get press coverage
- contact journalists
- press pitch
- media outreach
- tech press
- press release
- journalist outreach
- get featured
- press for launch
- media coverage
- tech journalist
- get written about
- press list

## Instructions

### Why Press Matters

Press gets you mainstream users outside your niche bubble — people you can't reach through Product Hunt or Hacker News. A single article in a major outlet can drive 50,000+ visitors over weeks.

### Why Generic Press Emails Fail

DO NOT email tips@thenextweb.com or press@techcrunch.com. These are black holes. A lot goes in, nothing comes out.

### Step 1: Find the Right Journalist

The key insight: every journalist has a niche. Find the one who covers YOUR niche.

1. Use `web_search` to find recent articles about products similar to yours:
   - Search: `"[your niche] site:techcrunch.com"` or `"[your niche] site:theverge.com"`
   - Search: `"[similar product name] review"`
2. Note the journalist's name from each relevant article
3. Use `browser_navigate` to check their Twitter/X profile — most journalists list their beat and contact preferences
4. Look for their personal email in:
   - Twitter bio
   - Personal website/blog
   - LinkedIn profile
   - Author page on the publication
5. Build a list of 10-20 journalists, ranked by relevance to your product

### Step 2: Craft the Pitch

**Subject line**: Short, specific, newsworthy. Not "Check out my app!" but "New app lets digital nomads find cities by internet speed" — describe what it does in one line.

**Body structure**:
```
Hi [First Name],

I saw your article about [specific article they wrote]. [One sentence about why you liked it / why it's relevant].

I built [product name] — [one sentence describing what it does]. [One sentence about why it matters / what's unique].

[Link to product]
[Link to high-res screenshots/video]

Would love to get your thoughts.

[Your name]
```

**Rules**:
- KEEP IT SHORT. Journalists get hundreds of emails. 5 sentences max.
- Make it about THEM, not you. Reference their specific work.
- Include everything they need: link, screenshots, video. Don't make them ask.
- Never say "revolutionary" or "disrupting". Show, don't tell.
- Personalize EVERY email. Mass pitches are deleted instantly.

### Step 3: When to Send

- **Before launch**: Give journalists 1-2 days heads up so they can have an article ready for launch day.
- **Day of launch**: Follow up with "We're live on Product Hunt today" + link.
- **After traction**: "We hit #1 on Product Hunt with X upvotes" or "50,000 users signed up in the first week" — traction IS the story.

### Step 4: Follow Up

- If no response after 3-4 days, send ONE follow-up. Short: "Just checking if you saw my note about [product]. Happy to answer any questions."
- If still no response, move on. Don't spam.
- If they write about you, THANK THEM. Publicly on Twitter and privately via email. Build the relationship for future launches.

### Step 5: Control the Narrative

- You set the angle of the story. Prepare a clear narrative before reaching out.
- Check what types of articles the journalist writes before you talk to them.
- Fact-check articles about you after publication. Ask for corrections if needed.
- Press can flip negative. They like making things sound dramatic for page views. Be prepared.

### Platforms to Target (by audience)

| Outlet | Audience | Traffic potential |
|--------|----------|-------------------|
| TechCrunch | Tech/startup insiders | 100K+ |
| The Verge | Tech mainstream | 200K+ |
| Hacker News (organic) | Developers | 50-100K |
| Product Hunt | Early adopters | 10K |
| The Next Web | European tech | 50K+ |
| Wired | Tech + culture | 100K+ |
| Ars Technica | Deep tech | 50K+ |
| Niche blogs | Your specific audience | Varies, often highest conversion |

### Anti-Patterns

- Don't write a "press release" in formal corporate speak. Write like a human.
- Don't email 100 journalists the same template. They talk to each other and will notice.
- Don't offer "exclusive" to multiple journalists simultaneously.
- Don't get angry if press is negative. Respond with grace. Fix the issues they mention.
- Don't rely solely on press. It's a kickstart, not a growth strategy. Product quality is what retains users.

### Tools to Use

- `web_search` — Find journalists and their articles
- `browser_navigate` — Visit journalist profiles, find contact info
- `email_send` — Send personalized pitches
- `prospect_search` — Save journalist contacts to pipeline
- `prospect_outreach` — Track pitch status and follow-ups
- `affiliate_pitch` — Generate pitch copy variations

## Verify

- The actual channel was reached (post URL, message ID, or platform-side confirmation captured), not just a draft saved locally
- Targeting parameters (subreddit, hashtag, audience, time zone) match what the press-outreach guide prescribes for the chosen platform
- Copy was checked against the platform's character/format limits before posting; the final character count is recorded
- Engagement plan for the first 1-2 hours after posting is written down with specific actions, not 'monitor and reply'
- At least one platform-specific anti-pattern from the skill (e.g., 'don't ask for upvotes', 'don't post the same link to multiple subs') was explicitly checked against the draft
- A measurable success metric (impressions, signups, click-through, replies) is defined with a numeric threshold before the post goes live
