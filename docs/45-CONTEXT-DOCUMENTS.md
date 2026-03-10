# 45 — Context Documents

> Inspired by [Arvid Kahl's Claude Code productivity tips](https://x.com/arvidkahl/status/2031457304328229184):
> maintain structured context documents that describe your product, customers,
> visual style, and domain model — so the agent always has the full picture.

## Overview

EloPhanto maintains a set of **context documents** in `knowledge/system/` that give the
agent deep self-awareness of what it is, who it serves, how it looks, and how its
parts connect. These documents are auto-indexed into the knowledge base and surface
in the system prompt when relevant.

Unlike ad-hoc knowledge that accumulates from tasks, context documents are
**curated reference material** — the agent's equivalent of a product team's shared
docs folder.

## Documents

| File | Purpose | Equivalent |
|------|---------|------------|
| `capabilities.md` | Full feature inventory — every tool, channel, provider, and capability | platform-docs.md |
| `icps.md` | Ideal Customer Profiles — who uses EloPhanto, what they need, how they work | ICPs.md |
| `styleguide.md` | Visual and brand identity — colors, typography, tone, UI patterns | styleguide.md |
| `data-reference.md` | Domain model — how sessions, channels, knowledge, identity, and tools relate | data-reference.md |
| `architecture.md` | System layers and component relationships (already existed) | architecture.md |
| `conventions.md` | Code style, patterns, and development practices (already existed) | conventions.md |

## How They're Used

1. **Knowledge indexer** picks them up from `knowledge/system/` with `scope: system`
2. **Semantic search** surfaces relevant sections when the agent plans tasks
3. **Autonomous mind** references them for self-aware behavior (posting about capabilities, building UIs consistent with the styleguide, targeting the right audience)
4. **Working memory** loads relevant chunks before each LLM call
5. **Organization children** inherit these docs for consistent behavior across specialists

## capabilities.md

Complete inventory of every tool (grouped by category), channel adapter, LLM provider,
skill, and integration. Updated whenever tools are added or features ship.

Sections:
- System tools (filesystem, shell, vault)
- Browser tools (49 tools via Node.js bridge)
- Desktop tools (11 tools via AppleScript/accessibility)
- Knowledge & skills tools
- Self-development tools
- Communication tools (email, commune)
- Payment tools (Solana + Base/EVM)
- Deployment tools
- Organization & swarm tools
- Experimentation tools
- Scheduling & mind tools
- MCP adapter
- TOTP tools
- Channel adapters (6)
- LLM providers (4)
- Skills (147)
- Security features

## icps.md

Dossier-style profiles for each target user type. Each profile includes:
- **Who they are** — role, motivation, daily workflow
- **What they want** — not features, but autonomous outcomes
- **How EloPhanto delivers** — specific capabilities, tools, and workflows
- **Where to reach them** — platforms, communities, content they consume
- **What convinces them** — proof points, demos, messaging that resonates

All ICPs share a common thread: they want an **autonomous digital worker** that
operates independently — builds, earns, promotes, trades, and grows while they
do other things (or sleep).

Profiles:
1. The Autonomous Business Operator — launches businesses at machine speed
2. The Agent Economy Participant — agent with its own wallet, DeFi strategies
3. The One-Person Company — digital co-founder that handles everything they can't
4. The AI-Native Builder — open source agent they can fully control and extend
5. The Delegator (Non-Technical) — tells it what to do via Telegram, expects results
6. The AI-Curious Professional — knowledge worker who wants AI to save real hours
7. The Business Leader / Executive — wants an AI workforce at 1% the cost of headcount
8. The Creator / Influencer — creates content, agent handles distribution everywhere

## styleguide.md

Visual and brand identity reference for all generated UIs — landing pages, dashboards,
marketing sites, social media graphics.

Sections:
- Color palette (dark-first, electric purple accent)
- Typography (monospace headings, Inter/Geist body)
- Component patterns (terminal-style code blocks, card grids, stat strips)
- Tone of voice (technical but accessible, no corporate speak, first-person)
- Social media style (scroll-stopping hooks, concrete proof over hype)
- Anti-patterns (no emojis unless asked, no "AI-powered" buzzwords, no stock photos)

## data-reference.md

Domain model reference explaining relationships between core concepts that aren't
obvious from code alone.

Sections:
- Session vs conversation vs channel (isolation model)
- Knowledge chunks → skills → tools (the intelligence stack)
- Identity → autonomous mind → goals (the agency stack)
- Gateway → adapters → sessions (the communication stack)
- Vault → payments → approvals (the trust stack)
- Organization → children → trust scoring (the delegation model)
- Swarm → worktrees → PRs (the coding model)

## Maintenance

These documents should be updated when:
- New tools or capabilities are added
- The target audience shifts
- Brand/visual direction changes
- Architecture evolves significantly

The `knowledge_drift` system (see [05-KNOWLEDGE-SYSTEM.md](05-KNOWLEDGE-SYSTEM.md))
can flag these documents as stale when covered source files change, using the
`covers:` frontmatter field.
