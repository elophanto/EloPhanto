# Agent Organization

## Description
Best practices for spawning, managing, and teaching persistent specialist
child agents (marketing, research, design, etc.) through the organization system.

## Triggers
- organization
- specialist
- marketing agent
- research agent
- design agent
- team
- delegate work
- spawn specialist
- child agent

## Instructions

### Organization vs Swarm
- **Organization** (this skill) — persistent EloPhanto clones for domain work (marketing, research, design, anything). Own identity, knowledge vault, autonomous mind. They learn from feedback and work proactively.
- **Swarm** — ephemeral external coding agents (Claude Code, Codex, Gemini CLI) for code tasks. No learning, no persistence.

If the task is domain expertise → organization. If the task is code → swarm.

### When to Spawn Specialists
1. **Domain-specific work** — marketing strategy, competitive research, design audits, content creation
2. **Recurring work** — tasks that will happen repeatedly (the specialist accumulates knowledge over time)
3. **Parallel domain work** — "research competitors AND draft marketing plan" → spawn both
4. **Proactive monitoring** — "keep an eye on competitor pricing" → specialist with autonomous mind

### When NOT to Spawn
- Quick one-off tasks you can handle directly
- Coding tasks (use swarm instead)
- Tasks that need your tools directly (browser, email, payments)

### Spawning a Specialist

Use `organization_spawn` with a clear role and purpose:
- **role** — short identifier: "marketing", "research", "design", "content"
- **purpose** — what this specialist does (becomes their identity)
- **seed_knowledge** — relevant knowledge files to copy from your vault

The specialist goes through first awakening, discovers its identity, and is ready to work.

If a specialist for the role already exists, it's reused (restarted if stopped). Don't spawn duplicates.

### Delegating Tasks

Use `organization_delegate` with either `role` (auto-resolves) or `child_id`:
- Be specific about the task — "Create a 5-post content calendar for next week targeting developer audience"
- Include constraints — "Focus on X and LinkedIn, keep posts under 280 chars for X"
- Reference context — "Use the brand guidelines in your knowledge vault"

### Reviewing Output

Always review specialist output using `organization_review`:
- **Approve with feedback** — reinforces good behavior, optional praise or refinement notes
- **Reject with specific reason** — the rejection becomes a correction file in the specialist's knowledge vault. Be specific about what went wrong and what the correct approach is.

Good rejection: "Post exceeded X's 280 char limit. Always check platform character limits: X=280, LinkedIn=3000, Mastodon=500."
Bad rejection: "This is wrong."

### Teaching

Use `organization_teach` to proactively push knowledge:
- Brand guidelines, style guides, platform rules
- Domain-specific knowledge the specialist needs
- Corrections that apply broadly (not tied to a specific task)

### Trust Scoring
- Trust = approved_count - rejected_count
- New specialists (trust < 10) — review all output
- Trusted specialists (trust >= 10) — eligible for auto-approve
- Low trust (negative) — may need re-seeding with corrected knowledge

### Anti-Patterns
- **Spawning too many specialists** — each is a full process with its own LLM budget. Respect max_children.
- **Vague delegation** — "do marketing" is too broad. Break into specific tasks.
- **Not reviewing output** — the feedback loop is how specialists learn. Skip review = no learning.
- **Rejecting without explanation** — "rejected" teaches nothing. Always include specific feedback.
- **Duplicating roles** — check `organization_status` before spawning. One specialist per role.

## Verify

- The intended other agent / tool / channel actually received the message; an ack, message ID, or response payload is captured
- Identity, scopes, and permissions used by the call were the minimum required; over-permissioned tokens are called out
- Failure handling was exercised: at least one retry/timeout/permission-denied path is shown to behave as designed
- Hand-off context passed to the next actor is complete enough that the receiver could act without a follow-up question
- Any state mutated (config, memory, queue, file) is listed with before/after values, not just 'updated'
- Sensitive material (keys, tokens, PII) was redacted from logs/transcripts shared in the verification evidence
