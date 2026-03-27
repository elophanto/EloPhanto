---
name: product-launch
description: Multi-platform product launch playbook. Step-by-step guides for launching on Product Hunt, Hacker News, Reddit, BetaList, and Twitter. Timing, title craft, engagement strategy, what not to do. Based on levelsio's MAKE handbook.
---

## Triggers

- launch product
- product launch
- launch on product hunt
- launch on hacker news
- launch on reddit
- show hn
- product hunt launch
- hacker news launch
- betalist
- launch strategy
- launch plan
- launch my app
- launch my site
- launch my startup
- go live
- ship it
- announce product
- promote product
- get visibility
- get users
- first users
- launch day

## Instructions

### Pre-Launch Checklist

Before launching ANYWHERE, verify ALL of these:

1. **Product actually works** — Go through the entire user flow as a new user. Not just "it loads". Every button, form, payment flow. Test on mobile too.
2. **Fix critical bugs** — It doesn't need to be perfect, but it must not crash. Users forgive rough edges, not broken core flows.
3. **Landing page is clear** — A stranger should understand what the product does in 5 seconds. One sentence above the fold. No jargon.
4. **Call-to-action is obvious** — Big colored button. "Try it free", "Get started", "Sign up". Not hidden in a menu.
5. **Email capture works** — Even if they don't sign up, capture their email. Use a contextual offer: "Get notified when we add [specific feature]" — not "subscribe to our newsletter".
6. **Analytics are set up** — Google Analytics or Amplitude at minimum. You need to know how many people visit, where they come from, and what they do.
7. **Server can handle traffic** — Reddit can send 25,000 simultaneous users. HN sends 1,000. PH sends 300. If you're on shared hosting, you will crash. Use static pages where possible.
8. **Feedback widget is live** — Olark, Intercom, or a simple mailto link. Let users tell you what's broken. They become your 24/7 testing army.

### Launch Strategy: Launch Early, Launch Often

- Your first launch is NOT your only launch. Plan to launch multiple times on different platforms over weeks.
- Each major update is a new launch opportunity. "2.0", "3.0", etc.
- Order: BetaList (small, early adopters) -> Product Hunt (tech crowd, press) -> Hacker News (developer audience) -> Reddit (mass market) -> Press outreach
- Space them out. Don't launch everywhere on the same day — you can't be in all comment sections at once.

---

### Launching on Product Hunt

**Timing**: Product Hunt resets at midnight PST (San Francisco time). Submit at 00:00:01 PST for maximum voting window. Due to time zones, this means staying up late or waking early.

**Preparation**:
1. Use `browser_navigate` to go to producthunt.com and submit the product
2. **Name**: Use your product name. If relaunching, add "2.0" or "3.0"
3. **Tagline**: 60 characters max. Must be understandable by non-users. Use simple words, add emojis. Example: "Find the best place to live, work, and play" NOT "An algorithmic machine learning application for photos"
4. **Thumbnail**: Use an animated GIF if possible (convert a short demo video with GIPHY Capture). Square format. Eye-catching.
5. **Gallery**: 8-16 high-res screenshots. Zoom in browser so they're crisp. Show core functionality, not marketing fluff.
6. **Video**: Optional but powerful. 30 seconds max. Muted autoplay on desktop. Show the product working, not a talking head.

**Launch Day Engagement**:
1. Post a maker comment IMMEDIATELY after launch. Use this format:
   - Who you are (1 line)
   - The problem you're solving
   - The solution you built
   - What's next / future plans
   - Ask for feedback
2. Reply to EVERY comment. Be polite and humble. You're a guest inviting people into your app.
3. Share on Twitter, don't ask for upvotes explicitly. "My new app is on Product Hunt today" is fine. "Please upvote" is not.
4. If you have an email list, send a note. Don't ask for votes. They'll do it if they like it.
5. Stay in comments ALL DAY. Answer questions, take feature suggestions, fix bugs people report in real-time.

**What NOT to do**:
- Don't buy votes or use voting rings. PH detects this and will penalize you.
- Don't brag or market. Be a host, not a salesperson.
- Don't launch if your product isn't functional. An email signup box is NOT a product.

**Expected results**: Top of PH = ~10,000 visitors, ~300 simultaneous, a percentage signing up. Tech journalists watch PH for stories — expect press articles within days.

---

### Launching on Hacker News

**Format**: Use the "Show HN" tab. Title format:

GOOD: `Show HN: I made a site that lets you subscribe to food delivery for your pet`
BAD: `Petsy.com - The best food delivery for pets`

The personal, humble format works. HN hates marketing speak.

**Timing**: Submit and let it organically reach the front page. Getting 5 upvotes spread over the first hour from real people usually gets you to page 1.

**Engagement**:
1. Don't post your own link then immediately upvote it from other accounts. HN detects voting rings and will kill your post.
2. If it gets comments, reply honestly. HN is brutally honest. They'll tear your product apart. Don't fight back — listen, fix, thank.
3. If it doesn't take off on first try, resubmit in a week with a different title. HN allows resubmissions. Different day, different time, different angle.

**What to expect**:
- HN front page = 50,000-100,000 visitors, 1,000 simultaneous users
- 5-10x Product Hunt traffic
- Your server WILL be tested. Make pages static if possible.
- Comments will be harsh but honest. This is the most valuable feedback you'll get.
- HN audience skews technical. If your product is for developers, this is your best launch platform.

**HN zeitgeist matters**: HN has strong opinions about what's interesting RIGHT NOW. Privacy tools do well when there's a privacy scandal. Open source tools do well when there's backlash against big tech. Read the front page for a week before launching to understand the current mood.

---

### Launching on Reddit

**Subreddit selection is everything**:
1. Find the most specific subreddit for your product first. Pet food delivery? Start with r/pets, not r/startups.
2. Then try broader: r/startups, r/SideProject, r/InternetIsBeautiful, r/DataIsBeautiful
3. Title must be personal and humble: "Hi r/pets! I made a site that lets you subscribe to food delivery for your pet"

**Traffic warning**: Reddit front page = 50,000-500,000 visitors, 5,000-25,000 simultaneous. Most servers crash. Prepare:
- Make the landing page static HTML if possible
- Use a CDN (Cloudflare free tier)
- Keep the main page light (no heavy JavaScript frameworks for the landing)

**Engagement**: Jump into comments immediately. Reddit is a hivemind — if early comments are negative, the whole post dies. If early comments are positive, it snowballs. Be in there being helpful from minute one.

**What NOT to do**:
- Don't post the same link to multiple subreddits at once. Reddit marks this as spam.
- Don't use a brand-new account. Build some karma first by being a real person on Reddit.
- Don't ask for upvotes. Ever.

---

### Launching on BetaList

- Submit before bigger launches. BetaList gets you 500-1,000 targeted early adopters.
- Unless you pay (~$129), you'll wait ~2 months in queue.
- Great for getting initial beta testers before the big PH/HN launch.
- Product must be new. Doesn't need to be in beta anymore despite the name.

---

### Cross-Platform Launch Timeline

For a bootstrapped product, this is the recommended order:

| Week | Platform | Goal |
|------|----------|------|
| 1 | BetaList | Get 100-500 beta testers, fix bugs from feedback |
| 2-3 | Fix bugs, add features based on beta feedback | Improve product |
| 4 | Product Hunt | Big launch day, engage press, collect emails |
| 5 | Hacker News | Developer traction, honest feedback |
| 6 | Reddit (niche sub) | Mass market validation |
| 6+ | Reddit (broader), press outreach | Scale visibility |

### Post-Launch (Critical)

Most sites see a massive traffic drop after launch day. To retain:
1. **Email the visitors you captured** — Not immediately, but within 2 weeks. Bring them back with a new feature or update.
2. **Keep shipping** — Post updates on Twitter. "Just shipped [feature]" gets more engagement than promotional posts.
3. **Re-launch on updates** — Every major version is a new Product Hunt/HN launch opportunity.
4. **Be organic** — If the product is great, people will share it. Don't fake virality. Build something worth talking about.

### Tools to Use

- `browser_navigate` — Submit to platforms
- `twitter_post` — Announce launch, share updates
- `email_send` — Press outreach, user re-engagement
- `web_search` — Research platform timing, journalist contacts
- `affiliate_pitch` — Generate platform-appropriate copy
- `deploy_website` — Deploy landing page
- `replicate_generate` — Create thumbnails/screenshots

### Philosophy (from levelsio)

> "The most elementary mistake people still make is not sharing their ideas. No, people won't steal your idea if they like it. And even if they do, they probably can't execute it as well as you. Ideas are a dime a dozen. Everything is about how you execute."

> "Don't buy fake upvotes, likes, followers. If your app was good from the start, it wouldn't NEED any artificial following. It could push itself just by being great."

> "Be real. Be organic. Create traction by making a great product that is considerably better than the competition, easier to use and more original."
