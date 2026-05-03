# Prospecting

## Description
Autonomous outreach system for finding work, evaluating opportunities, and managing
a prospect pipeline. Searches freelance platforms, bounty boards, and Agent Commune,
then sends personalized outreach and tracks conversions.

## Triggers
- prospect
- prospecting
- outreach
- freelance
- bounty
- find work
- find clients
- lead generation
- pipeline
- cold email
- find opportunities
- search for gigs

## Instructions

### Overview

You have 4 prospecting tools for managing a structured pipeline:
- `prospect_search` — save discovered opportunities to the database
- `prospect_evaluate` — score opportunities against your capabilities
- `prospect_outreach` — log outreach activity (emails sent, replies received)
- `prospect_status` — view pipeline, get details, see conversion metrics

The actual discovery happens via your browser tools and Agent Commune tools.
The actual outreach happens via `email_send`. The prospecting tools track the metadata.

### Phase 1: Discovery

Search for opportunities using browser tools, then save them with `prospect_search`.

**Sources to search:**
1. **Freelance platforms** — Browse Upwork, Freelancer, Toptal for relevant gigs
2. **Bug bounties** — Check Immunefi, Code4rena, HackerOne for active programs
3. **GitHub bounties** — Search GitHub issues with bounty labels
4. **Agent Commune** — Use `commune_search` for agent-to-agent job postings
5. **Partnership opportunities** — Search for "looking for AI agent" or "AI automation" posts

After finding prospects via browser, batch-save them:
```
prospect_search(prospects=[
  {title: "Build Solana dashboard", source: "freelance", platform: "upwork",
   url: "https://...", description: "...", budget_min: 500, budget_max: 2000,
   required_skills: ["solana", "react"]}
])
```

### Phase 2: Evaluation

For each new prospect, evaluate against your actual capabilities.

1. Use `identity_status` or `self_list_capabilities` to check what you can do
2. Compare required skills to your skill list
3. Score honestly — only pursue what you can deliver

```
prospect_evaluate(
  prospect_id: "p_abc123",
  match_score: 0.85,
  match_reasoning: "Strong match: Solana dev skills, React, TypeScript. Can use jupiter-defi and solana-development skills.",
  priority: "high",
  decision: "pursue"
)
```

**Rules:**
- Skip anything below 0.5 match score (decision: "skip")
- Defer anything you're unsure about (decision: "defer")
- Never misrepresent capabilities

### Phase 3: Outreach

For high-priority evaluated prospects, send personalized outreach.

1. Draft a personalized email referencing the specific opportunity
2. Mention relevant skills and experience
3. Include payment acceptance (USDC on Solana/Base)
4. Send via `email_send`
5. Log via `prospect_outreach`

```
# 1. Send the email
email_send(to: "client@example.com", subject: "Re: Your Solana project",
  body: "Hi, I noticed your Solana DEX aggregator project...")

# 2. Log the outreach
prospect_outreach(prospect_id: "p_abc123", action: "email_sent",
  channel: "email", content_preview: "Hi, I noticed your Solana DEX...")
```

**Outreach rules:**
- Max 10 outreach emails per day (enforced by the tool)
- Always personalize — reference the specific opportunity
- Never send template/generic messages
- Include your Agent Commune profile link if available
- Mention you accept crypto payments (USDC)

### Phase 4: Follow-up & Tracking

1. Check `prospect_status list` for prospects with status "outreach_sent"
2. If no reply after 3 days, send ONE follow-up via `email_send`, then log as `follow_up`
3. When `email_monitor` detects a reply from a known prospect email, update via `prospect_outreach(action: "reply_received")`
4. Never follow up more than once — if no reply after follow-up, let it go

### Phase 5: Conversion

When a prospect agrees to work:
1. Update status: `prospect_outreach(action: "status_change", new_status: "converted")`
2. Create a payment request: `payment_request(action: "create", amount: X, token: "USDC", memo: "Project description")`
3. Send payment details via `email_send`
4. For larger projects, create a goal with checkpoints

### Heartbeat Integration

When running autonomously via heartbeat, follow this cycle:

1. Check `prospect_status metrics` — understand current pipeline state
2. If pipeline has < 10 active prospects: search for 5 new opportunities
3. Evaluate any unevaluated prospects (status: "new")
4. Send outreach to top 3 high-priority evaluated prospects (if under daily limit)
5. Follow up on prospects with outreach_sent > 3 days ago
6. Check email for replies from known prospect contact_emails
7. Report summary to user if anything noteworthy happened

### Anti-Patterns

- **Never spam** — Max 10 outreach/day, always personalized
- **Never lie about skills** — Only pursue match_score > 0.5
- **Never follow up more than once** — One follow-up after 3 days, that's it
- **Never send outreach without evaluating first** — Always score before contacting
- **Don't overload the pipeline** — If 20+ prospects are in outreach_sent, focus on follow-up instead of new discovery
- **Respect opt-outs** — If someone says "not interested", mark as rejected, never contact again

## Verify

- The outbound message was actually sent (timestamp + recipient + channel) or the response was posted to the user (ticket ID), not held in a draft
- The recipient/segment matches the criteria in the prospecting guide; mis-targeted contacts are excluded with a reason
- Personalization references at least one verifiable fact about the recipient (role, recent event, prior message), not a generic token
- Compliance constraints relevant to the channel (CAN-SPAM, GDPR, region opt-in, NDA, disclosure) were checked off explicitly
- A follow-up cadence and stop-condition is set, so silent recipients are not pinged indefinitely
- Outcome (reply, booked meeting, resolved/closed) is logged in the system of record, not only in chat
