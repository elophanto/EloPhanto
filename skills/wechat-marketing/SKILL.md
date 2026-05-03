---
name: wechat-marketing
description: Expert WeChat Official Account strategist for content marketing, subscriber engagement, automation workflows, and conversion optimization in the Chinese market. Adapted from msitarzewski/agency-agents.
---

## Triggers

- wechat marketing
- wechat official account
- wechat OA
- wechat strategy
- wechat content
- wechat subscribers
- wechat mini program
- wechat automation
- china marketing
- chinese social media
- wechat engagement
- wechat conversion
- wechat menu
- wechat articles
- wechat community

## Instructions

### Subscriber and Business Analysis
1. Assess current subscriber demographics, engagement metrics, and content performance using `browser_navigate`.
2. Define clear business objectives: brand awareness, lead generation, sales, or retention.
3. Use `web_search` to research subscriber preferences, competitor OAs, and market trends in the Chinese market.
4. Identify differentiation opportunities against competitor Official Accounts.
5. Save analysis using `knowledge_write`.

### Content Strategy and Calendar
1. Define 4-5 content pillars aligned with business goals and subscriber interests.
2. Follow the 60/30/10 rule: 60% value content, 30% community/engagement content, 10% promotional.
3. Plan optimal posting frequency (typically 2-3 per week) and timing.
4. Build a 3-month rolling editorial calendar with themes, content ideas, and seasonal integration.
5. Design custom menus for easy navigation, automation, and Mini Program access.

### Content Creation and Optimization
1. Write compelling headlines with emotional hooks and clear structure.
2. Create scannable content: clear headlines, bullet points, visual hierarchy.
3. Maintain consistent visual branding: typography, cover images, design elements.
4. Optimize for internal search: strategic keyword placement in titles and body.
5. Include interactive elements: polls, questions, CTAs that drive engagement.
6. All content must be mobile-optimized (primary WeChat consumption method).
7. Include clear CTAs aligned with business objectives in every piece of content.

### Automation and Engagement Building
1. Design auto-reply system: welcome message, common questions, menu guidance.
2. Set up keyword automation for popular queries and subscriber interactions.
3. Implement subscriber segmentation for targeted, relevant communication.
4. Integrate Mini Programs for enhanced functionality and user retention where applicable.
5. Build community features: encourage feedback, UGC, and community interaction.
6. Use `browser_navigate` for WeChat management and engagement.

### Mini Program Integration
1. Plan Mini Program features that enhance subscriber experience and data collection.
2. Target 40%+ of subscribers using integrated Mini Programs.
3. Design intuitive navigation between OA content and Mini Program features.
4. Track Mini Program engagement and conversion metrics.

### Performance Analysis and Optimization
1. Conduct weekly analytics review via `browser_navigate`: open rates, CTR, completion rates, subscriber trends.
2. Identify top-performing content themes, formats, and posting times.
3. Monitor subscriber feedback through messages, comments, and engagement patterns.
4. A/B test headlines, sending times, and content formats.
5. Scale successful content patterns and expand winning series.
6. Save performance reports using `knowledge_write`.

### Tools Reference
- `web_search` for market research, competitor OA analysis, Chinese market trends
- `browser_navigate`, `browser_extract` for WeChat management, analytics, and engagement
- `knowledge_write` for persisting content strategies, calendars, and performance data
- `knowledge_search` for retrieving subscriber research and previous campaign data

## Deliverables

### WeChat OA Content Calendar
```markdown
# WeChat Official Account Calendar - Month [X]

## Content Pillars
1. [Pillar 1]: Industry insights and education (value content)
2. [Pillar 2]: Customer stories and community features
3. [Pillar 3]: Product/service updates and tips
4. [Pillar 4]: Interactive content and engagement drivers
5. [Pillar 5]: Seasonal/trending content

## Weekly Schedule
| Day | Content Type | Pillar | Format | CTA |
|-----|-------------|--------|--------|-----|
| Mon | Value article | Pillar 1 | Long-form + images | Read more / Share |
| Wed | Community | Pillar 2 | Customer story | Comment / Share |
| Fri | Engagement | Pillar 4 | Poll + Mini Program | Participate |

## Menu Architecture
- Menu 1: [Product/Service] -> Mini Program / Key pages
- Menu 2: [Resources] -> Best articles / Guides
- Menu 3: [Contact] -> Customer service / FAQ automation
```

### Subscriber Engagement Framework
```markdown
# WeChat Subscriber Journey

## New Subscriber
1. Auto-welcome message with value proposition and menu guide
2. First-week content series introducing brand and key resources
3. Keyword prompt for self-segmentation

## Active Subscriber
1. Regular content delivery (2-3x/week)
2. Interactive elements encouraging engagement
3. Mini Program integration for deeper value

## Conversion Path
1. Value content -> Interest signal (clicks, keywords)
2. Targeted follow-up based on segment
3. Conversion CTA (purchase, consultation, sign-up)
4. Post-conversion nurture and retention
```

## Success Metrics

- Open Rate: 30%+ (2x industry average)
- Click-Through Rate: 5%+ for links in articles
- Subscriber Retention: 95%+ (low unsubscribe rate)
- Subscriber Growth: 10-20% monthly organic growth
- Article Read Completion: 50%+ completion rate
- Menu Click Rate: 20%+ of followers using custom menu weekly
- Mini Program Activation: 40%+ of subscribers using integrated features
- Conversion Rate: 2-5% from subscriber to paying customer
- Lifetime Subscriber Value: 10x+ return on content investment

## Verify

- The actual channel was reached (post URL, message ID, or platform-side confirmation captured), not just a draft saved locally
- Targeting parameters (subreddit, hashtag, audience, time zone) match what the wechat-marketing guide prescribes for the chosen platform
- Copy was checked against the platform's character/format limits before posting; the final character count is recorded
- Engagement plan for the first 1-2 hours after posting is written down with specific actions, not 'monitor and reply'
- At least one platform-specific anti-pattern from the skill (e.g., 'don't ask for upvotes', 'don't post the same link to multiple subs') was explicitly checked against the draft
- A measurable success metric (impressions, signups, click-through, replies) is defined with a numeric threshold before the post goes live
