---
name: landing-page-launch
description: Pre-launch validation with landing pages. Build a landing page, capture emails, accept pre-orders, and validate demand before writing code. Based on levelsio's MAKE handbook.
---

## Triggers

- landing page
- pre-launch
- validate idea
- validate demand
- pre-order page
- coming soon page
- waitlist page
- email capture
- launch page
- validate startup
- test demand
- mvp validation
- idea validation
- build in public

## Instructions

### The Core Idea

Launch before you build. The fastest way to validate demand is to describe what you want to build, put up a landing page, and see if people will pay for it.

Levelsio announced his MAKE book with nothing but a tweet and a Typeform. People pre-ordered at $22.49. He collected $50,000+ in pre-orders before writing a single chapter.

### Step 1: Build the Landing Page

Use `deploy_website` to create a simple landing page with these elements:

**Above the fold (visible without scrolling)**:
1. **Headline**: What does it do? One sentence. "We pick up and deliver your bags at any address worldwide, within hours."
2. **Subheadline**: One more sentence of context. Keep it human.
3. **CTA button**: Big, colored, centered. "Get Started", "Pre-Order", "Join Waitlist"

**Below the fold**:
4. **How it works**: 3 steps with icons
5. **Social proof**: Testimonials, logos, numbers (add these after launch)
6. **FAQ**: Address top objections

**Design rules**:
- Use the `ui-ux-pro-max` skill for design system
- Mobile-first. More than 50% of traffic will be mobile.
- Fast loading. No heavy frameworks for a landing page. Static HTML + Tailwind or similar.
- Clear value proposition in 5 seconds or the visitor bounces

### Step 2: Email Capture

Every landing page MUST capture emails. But "subscribe to our newsletter" doesn't work. Instead, offer specific value:

GOOD: "Get a daily email of all new PHP jobs" (contextual, useful)
GOOD: "Send me a message when you have a special food discount in my area"
BAD: "Subscribe to our newsletter"

Implementation:
- Simple form with name + email
- Store in database or Google Sheets via API
- Send immediate confirmation email via `email_send`
- Segment by interest if possible (e.g., which feature they clicked on)

### Step 3: Accept Pre-Orders (Optional but Powerful)

If you want to validate willingness to pay (not just interest):
1. Add Stripe Checkout to the landing page
2. Set a pre-order price ($10-$50 depending on the product)
3. Be transparent: "This product doesn't exist yet. Your pre-order funds its development. We'll deliver by [date] or refund."
4. Pre-orders prove demand better than any survey or "interested" click

### Step 4: Announce

1. Tweet about it from your personal account. Be genuine: "I want to build [thing]. Here's a landing page to see if anyone wants it."
2. Post in relevant communities (not as marketing, but as "I'm exploring this idea, would you use it?")
3. Share with friends, colleagues, potential users directly

### Step 5: Measure and Decide

| Signal | Meaning |
|--------|---------|
| 0 signups | Either bad idea, bad landing page, or nobody saw it. Try a different angle. |
| 10-50 signups | Mild interest. Could be worth building if you're passionate. |
| 50-200 signups | Real interest. Worth building an MVP. |
| 200+ signups | Strong demand. Build it. |
| Pre-order payments | Validated demand. Definitely build it. |

### Build in Public

Levelsio's approach: build with your users, not for them.
- Share drafts/progress on Twitter as you build
- Let pre-order customers vote on features (Workflowy shared list, Google Doc)
- Send chapter/milestone updates to your email list
- Livestream development (optional but builds accountability)

This builds an audience BEFORE launch. When you launch for real, you already have fans.

### The MVP is NOT a Landing Page

Critical distinction: an email signup box is NOT a product. Don't "launch" a coming-soon page on Product Hunt. That's not a launch. A functional MVP that does one thing well — THAT is launch-ready.

The landing page validates demand. The MVP validates the solution. They're different steps:
1. Landing page → "Do people want this?" (pre-launch)
2. MVP → "Does this solution work?" (launch)

### Tools to Use

- `deploy_website` — Deploy the landing page to Vercel/Railway
- `email_send` — Confirmation emails, pre-order receipts
- `email_monitor` — Track signup notifications
- `twitter_post` — Announce and build in public
- `web_search` — Research competitors, validate niche
- `replicate_generate` — Create hero images/graphics
- `browser_navigate` — Set up Stripe, Typeform, analytics

### Philosophy

> "Before even writing a single line on it I announced this book and opened it up for pre-orders. The only thing people received after paying $22.49 immediately was an empty Workflowy list where they could write what the book should be about specifically. That gave me immediate feedback from customers. Just like a startup."

> "Make sure your MVP actually works and is not just a landing page that doesn't do anything. It should do something. It should have the core functionality working well to be useful for users."

> "Don't build on an MVP too long, a good rule of thumb is to spend max one month on it and launch."
