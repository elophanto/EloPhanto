---
name: runbook-marketing-campaign
description: Multi-channel marketing campaign runbook — coordinated content creation, platform-specific execution, and data-driven optimization. Adapted from msitarzewski/agency-agents.
---

## Triggers

- marketing campaign
- multi-channel campaign
- social media campaign
- content campaign
- growth campaign
- launch campaign
- cross-platform marketing
- campaign strategy
- campaign optimization
- brand campaign
- acquisition campaign
- viral campaign
- influencer campaign
- content marketing
- campaign analytics

## Instructions

This runbook covers launching a coordinated marketing campaign across multiple channels. Content needs to be platform-specific, brand-consistent, and data-driven. Duration: 2-4 weeks.

### Agent Roster

**Campaign Core** (use `organization_spawn`):
- Social Media Strategist: Campaign lead, cross-platform strategy
- Content Creator: Content production across all formats
- Growth Hacker: Acquisition strategy, funnel optimization
- Brand Guardian: Brand consistency across all channels
- Analytics Reporter: Performance tracking and optimization

**Platform Specialists**:
- Twitter Engager: Twitter/X campaign execution
- TikTok Strategist: TikTok content and growth
- Instagram Curator: Instagram visual content
- Reddit Community Builder: Reddit authentic engagement
- App Store Optimizer: App store presence (if mobile)

**Support**:
- Trend Researcher: Market timing and trend alignment
- Experiment Tracker: A/B testing campaign variations
- Executive Summary Generator: Campaign reporting
- Legal Compliance Checker: Ad compliance, disclosure requirements

### Week 1: Strategy & Content Creation

**Day 1-2 — Campaign Strategy** (parallel via `organization_delegate`):

Social Media Strategist:
- Campaign objectives and KPIs
- Target audience definition
- Platform selection and budget allocation
- Content calendar (4-week plan)
- Engagement strategy per platform

Trend Researcher:
- Trending topics to align with
- Competitor campaign analysis
- Optimal launch timing

Growth Hacker:
- Landing page optimization plan
- Conversion funnel mapping
- Viral mechanics (referral, sharing)
- Channel budget allocation

Brand Guardian:
- Campaign-specific visual guidelines
- Messaging framework
- Tone and voice for campaign
- Do's and don'ts

Legal Compliance Checker:
- Disclosure requirements
- Platform-specific ad policies
- Regulatory constraints

**Day 3-5 — Content Production** (parallel):

Content Creator: Blog posts, email sequences, landing page copy, video scripts, social media copy (platform-adapted)

Twitter Engager: Launch thread (10-15 tweets), daily engagement tweets, reply templates, hashtag strategy

TikTok Strategist: Video concepts (3-5 videos), hook strategies, trending audio/format alignment, posting schedule

Instagram Curator: Feed posts (carousel, single image), stories content, reels concepts, visual aesthetic guidelines

Reddit Community Builder: Subreddit targeting, value-first post drafts, comment engagement plan, AMA preparation

### Week 2: Launch & Activate

**Day 1 — Pre-Launch**: All content queued and scheduled, analytics tracking verified, A/B test variants configured, landing pages live and tested, team briefed.

**Day 2-3 — Launch** (all platform agents in parallel):
- Twitter Engager: Launch thread + real-time engagement
- Instagram Curator: Launch posts + stories
- TikTok Strategist: Launch videos
- Reddit Community Builder: Authentic community posts
- Content Creator: Blog post published + email blast
- Growth Hacker: Paid campaigns activated
- Analytics Reporter: Real-time dashboard monitoring

**Day 4-5 — Optimize**:
- Analytics Reporter: First 48-hour performance report
- Growth Hacker: Channel optimization based on data
- Experiment Tracker: A/B test early results
- Social Media Strategist: Engagement strategy adjustment
- Content Creator: Response content based on reception

### Week 3-4: Sustain & Optimize

Daily: Platform agents (engagement + posting), Analytics Reporter (daily snapshot), Growth Hacker (funnel optimization)

Weekly: Social Media Strategist (performance review), Experiment Tracker (A/B results + new tests), Content Creator (new content from performance data), Analytics Reporter (weekly campaign report)

End of Campaign: Analytics Reporter (comprehensive analysis), Growth Hacker (ROI + channel effectiveness), Executive Summary Generator (campaign executive summary), Social Media Strategist (lessons learned)

Use `knowledge_write` to persist campaign strategy, content calendar, performance reports, and lessons learned.

## Deliverables

- [ ] Cross-platform campaign strategy with KPIs
- [ ] Content calendar (4-week plan)
- [ ] Platform-specific content packages
- [ ] Landing pages optimized and live
- [ ] A/B test variants configured
- [ ] Daily/weekly performance reports
- [ ] Campaign executive summary
- [ ] Lessons learned and recommendations

## Success Metrics

| Metric | Target |
|--------|--------|
| Total reach | Based on budget |
| Engagement rate | > 3% average across platforms |
| Click-through rate | > 2% on CTAs |
| Conversion rate | > 5% landing page |
| Cost per acquisition | Below target CAC |
| Brand sentiment | Net positive |
| A/B tests completed | >= 5 |

### Platform-Specific KPIs

| Platform | Primary KPI | Secondary KPI |
|----------|------------|---------------|
| Twitter/X | Impressions + engagement rate | Follower growth |
| TikTok | Views + completion rate | Follower growth |
| Instagram | Reach + saves | Profile visits |
| Reddit | Upvotes + comment quality | Referral traffic |
| Email | Open rate + CTR | Unsubscribe rate |
| Blog | Organic traffic + time on page | Backlinks |
| Paid ads | ROAS + CPA | Quality score |

## Verify

- The actual channel was reached (post URL, message ID, or platform-side confirmation captured), not just a draft saved locally
- Targeting parameters (subreddit, hashtag, audience, time zone) match what the runbook-marketing-campaign guide prescribes for the chosen platform
- Copy was checked against the platform's character/format limits before posting; the final character count is recorded
- Engagement plan for the first 1-2 hours after posting is written down with specific actions, not 'monitor and reply'
- At least one platform-specific anti-pattern from the skill (e.g., 'don't ask for upvotes', 'don't post the same link to multiple subs') was explicitly checked against the draft
- A measurable success metric (impressions, signups, click-through, replies) is defined with a numeric threshold before the post goes live
