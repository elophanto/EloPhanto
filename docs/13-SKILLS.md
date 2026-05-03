# EloPhanto — Skills System

## Overview

Skills are best-practice guides that teach the agent HOW to do specific types of work well. Each skill is a `SKILL.md` file containing triggers, step-by-step instructions, and examples. The agent reads relevant skills before starting a task, following the same pattern used by Claude's computer-use skills.

Skills are not tools — they don't execute code. They are prompt-injected knowledge that improves the agent's output quality for specific task categories.

## Architecture

```
skills/
  _template/              # Template for creating new skills
    SKILL.md
  browser-automation/     # Bundled: browser best practices
    SKILL.md
  code-quality/           # Bundled: coding standards
    SKILL.md
  research/               # Bundled: information gathering
    SKILL.md
  file-management/        # Bundled: file operations
    SKILL.md
  frontend-design/        # Installed: from external repo
    SKILL.md
```

All skills use the same `SKILL.md` convention regardless of origin (bundled, installed, or user-created).

## SKILL.md Format

Every skill must have a `SKILL.md` file in its directory with these sections:

```markdown
# Skill Name

## Description
One-line description used in the system prompt.

## Triggers
Keywords that activate this skill:
- keyword1
- keyword2
- "multi-word phrase"

## Instructions
Step-by-step best practices...

## Examples
Good and bad examples...

## Verify
Optional. Machine-actionable post-conditions (one per bullet) the agent
must evaluate before reporting the task complete. See "Verify gate"
below.

## Notes
Additional context...
```

The `Description`, `Triggers`, and `Verify` sections are parsed automatically by the SkillManager. The rest is read by the agent when the skill is activated.

## Verify gate

A skill can declare post-conditions in a `## Verify` section. Each
bulleted (or numbered) item is one observable check. Example from
`api-testing`:

```markdown
## Verify

- Test suite was actually executed (output captured), not just written
- Every endpoint in the discovered inventory has at least one assertion
- Authentication/authorization paths are explicitly tested, not assumed
- Failing tests fail loudly — no silent skips or `xfail` without justification
- Performance assertions specify a numeric threshold (e.g. p95 < 200ms), not vague language
```

When a skill is auto-loaded **and** the match is high-confidence
(skill matcher score ≥ 6 — i.e. the user's intent strongly references
the skill, not an incidental keyword), the agent's system prompt gets
a `<verification_required>` block instructing the model to evaluate
each check by id and emit a `Verification: PASS / FAIL / UNKNOWN`
section in the final response. Failure means repair-and-recheck, not
"done."

The score gate is intentionally tighter than skill auto-load. Auto-load
remains permissive (better wrong skill than none); the verify gate
suppresses spurious checks on weak matches (e.g. "check the weather"
incidentally grazing `smart-contract-audit` at score 5).

168/168 non-template skills ship with a `## Verify` section: 4
hand-tuned reference implementations (`api-testing`,
`product-launch`, `evidence-collection`, `_template`) and 164
category-templated by an auto-seed pass (Solana/DeFi, marketing,
frontend/UI, accessibility, testing/QA, debugging, deployment,
research/writing, native/mobile/XR, agent infra, project/strategy,
experimentation, sales/support, language engineering, video/streaming,
Next.js, alphascala). Hand-tune individual skills as the gate surfaces
real problems.

## How Skills Work

### Discovery

On startup, the `SkillManager` scans the `skills/` directory for subdirectories containing `SKILL.md` files. It parses each file to extract the name, description, and triggers.

### System Prompt Integration

All discovered skills are listed in the system prompt under `<available_skills>`. When the current task matches skills, they appear in a `<recommended>` block:

```xml
<available_skills>
<recommended action='MUST skill_read BEFORE any other work'>
<skill source="local" tier="local" warnings="none">
<name>browser-automation</name>
<description>Best practices for reliable browser automation...</description>
</skill>
</recommended>
<other_skills>
  research — Information gathering, source hierarchy...
  ...
</other_skills>
</available_skills>
```

The system prompt includes a `<skills_mandatory>` section that gates all work behind skill reading — the agent MUST call `skill_read` for recommended skills before taking any other action. This prevents the agent from diving into tasks without loading relevant best practices first.

### Trigger Matching

The agent sees all available skills and their trigger keywords. When a user request matches a skill's triggers (e.g., "navigate to a website" matches the `browser-automation` skill), the agent uses the `skill_read` tool to load the skill's content before proceeding.

### Agent Tools

- `skill_read`: Read a skill's SKILL.md content by name
- `skill_list`: List all available skills with descriptions and triggers

## Installing External Skills

### From a Local Directory

```bash
elophanto skills install /path/to/skill-directory
```

### From a GitHub Repository

```bash
# Single skill from a repo
elophanto skills install https://github.com/user/repo/tree/main/skills/frontend-design

# All skills from a repo's skills/ directory
elophanto skills install https://github.com/user/repo
```

### Compatible Skill Sources

The skills system is compatible with any repository that uses the `SKILL.md` convention, including:

- [ui-skills.com](https://www.ui-skills.com/) — UI/frontend design skills
- Any GitHub repo with `skills/<name>/SKILL.md` structure
- Any repo using the `SKILL.md` convention

### From EloPhantoHub (Skill Registry)

```bash
# Search the registry
elophanto skills hub search "gmail automation"

# Install from the registry
elophanto skills hub install gmail-automation

# Update all hub-installed skills
elophanto skills hub update

# List hub-installed skills
elophanto skills hub list
```

### Managing Skills

```bash
# List all skills
elophanto skills list

# Read a skill
elophanto skills read browser-automation

# Remove a skill
elophanto skills remove frontend-design
```

## Creating Skills

### Manually

1. Create a directory in `skills/` with your skill name
2. Add a `SKILL.md` file following the template format
3. The skill is automatically discovered on next agent startup

### Via the Agent

The agent can create skills through the self-development pipeline when it learns a new pattern. For example, after completing several similar tasks, it can codify the approach into a skill:

```
User: You've handled several API integration tasks now. 
      Create a skill for API integration best practices.
Agent: [uses knowledge_write to create skills/api-integration/SKILL.md]
```

### Template

Use `skills/_template/SKILL.md` as a starting point for new skills.

## Bundled & Installed Skills

EloPhanto ships with 120+ skills across multiple categories:

### Core Skills (EloPhanto-native)

| Skill | Purpose |
|---|---|
| `python` | Python coding, EloPhanto plugin interface, async patterns, pytest |
| `typescript-nodejs` | TypeScript/Node.js patterns, Zod validation, Vitest testing |
| `browser-automation` | All 47 browser tools, evidence gating, login flows, debugging |
| `file-management` | File tools, shell integration, protected files awareness |
| `research` | Information gathering, source hierarchy, knowledge preservation |

### Development Skills (from external sources)

| Skill | Source | Purpose |
|---|---|---|
| `nextjs` | [gocallum/nextjs16-agent-skills](https://github.com/gocallum/nextjs16-agent-skills) | Next.js App Router, Server Components |
| `supabase` | [supabase/agent-skills](https://github.com/supabase/agent-skills) | Postgres best practices, RLS, indexing |
| `prisma` | gocallum/nextjs16-agent-skills | Prisma ORM v7 patterns |
| `shadcn` | gocallum/nextjs16-agent-skills | shadcn/ui component patterns |
| `react-best-practices` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | React optimization rules |
| `composition-patterns` | vercel-labs/agent-skills | React component architecture |
| `mcp-builder` | [anthropics/skills](https://github.com/anthropics/skills) | MCP server development guide |
| `webapp-testing` | anthropics/skills | Playwright-based web app testing |

### UI/Design Skills (from [ui-skills.com](https://www.ui-skills.com/) and others)

| Skill | Purpose |
|---|---|
| `frontend-design` | Production-grade frontend interfaces |
| `interface-design` | Dashboards, admin panels, SaaS apps |
| `interaction-design` | Microinteractions, motion design, transitions |
| `baseline-ui` | Opinionated UI baseline against AI-generated slop |
| `design-lab` | Interactive design exploration workflow |
| `ui-ux-pro-max` | Comprehensive UI/UX intelligence (50+ styles) |
| `wcag-audit-patterns` | WCAG 2.2 accessibility audits |
| `canvas-design` | Digital canvas design philosophy |
| `12-principles-of-animation` | Disney animation principles for web |
| `web-design-guidelines` | Vercel Web Interface Guidelines compliance |
| `fixing-accessibility` | Fix accessibility issues |
| `fixing-metadata` | Ship correct, complete metadata |
| `fixing-motion-performance` | Fix animation performance issues |
| `swiftui-ui-patterns` | SwiftUI views and components |

### Organization & Strategy Skills (adapted from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents), Apache 2.0)

57 specialized skills across 9 divisions, plus the NEXUS strategy system:

| Division | Skills | Examples |
|---|---|---|
| Engineering (11) | `ai-engineering`, `backend-architecture`, `devops-automation`, `frontend-development`, `mobile-app-development`, `senior-development`, `data-engineering`, `security-engineering`, `rapid-prototyping`, `technical-writing`, `autonomous-optimization` | Backend architecture patterns, CI/CD pipelines, security hardening |
| Design (8) | `brand-guardian`, `image-prompt-engineering`, `inclusive-visuals`, `ui-design`, `ux-architecture`, `ux-research`, `visual-storytelling`, `whimsy-design` | Brand identity systems, UX research methods, visual narratives |
| Marketing (11) | `app-store-optimization`, `content-creation`, `growth-hacking`, `instagram-marketing`, `reddit-marketing`, `social-media-strategy`, `tiktok-marketing`, `twitter-marketing`, `wechat-marketing`, `xiaohongshu-marketing`, `zhihu-marketing` | Platform-specific strategies, growth loops, content calendars |
| Product (4) | `behavioral-nudge`, `feedback-synthesis`, `sprint-prioritization`, `trend-research` | RICE scoring, nudge frameworks, trend analysis |
| Project Management (5) | `experiment-tracking`, `project-shepherding`, `project-management`, `studio-operations`, `studio-production` | A/B testing, stakeholder management, portfolio oversight |
| Support (6) | `analytics-reporting`, `executive-summaries`, `finance-tracking`, `infrastructure-maintenance`, `legal-compliance`, `support-response` | KPI dashboards, compliance audits, incident response |
| Testing (8) | `accessibility-auditing`, `api-testing`, `evidence-collection`, `performance-benchmarking`, `reality-checking`, `test-analysis`, `tool-evaluation`, `workflow-optimization` | Load testing, QA evidence, process efficiency |
| Specialized (9) | `agentic-identity`, `agent-orchestration`, `data-analytics`, `data-consolidation`, `lsp-engineering`, `report-distribution`, `sales-data-extraction`, `cultural-intelligence`, `developer-advocacy` | Trust systems, pipeline orchestration, LSP indexing |
| Spatial Computing (6) | `macos-metal`, `terminal-integration`, `visionos-spatial`, `xr-cockpit`, `xr-development`, `xr-interface` | Metal rendering, visionOS, WebXR, spatial UI |

**NEXUS Strategy System (15 skills)**:

| Skill | Purpose |
|---|---|
| `agency-strategy` | Master NEXUS strategy — 7-phase pipeline, 3 deployment modes, 50+ agent roster |
| `agency-phase-0-discovery` through `agency-phase-6-operate` | Phase-specific playbooks with agent activation sequences, quality gates, and decision logic |
| `agent-activation` | Copy-paste activation prompts for all agents with placeholder customization |
| `agent-handoff` | Structured handoff templates (standard, QA pass/fail, escalation) |
| `runbook-startup-mvp` | 4-6 week MVP build scenario (NEXUS-Sprint mode) |
| `runbook-enterprise-feature` | Enterprise feature development scenario |
| `runbook-marketing-campaign` | Multi-channel marketing campaign scenario |
| `runbook-incident-response` | P0-P3 incident response with severity-based team activation |

### Organization Role Templates

75 role templates in `knowledge/organization-roles/` provide full persona definitions for specialist agents spawned via `organization_spawn`. Each template preserves the complete agent personality, capabilities, workflows, deliverable templates, and success metrics from the source material.

When the master spawns a specialist (e.g., `organization_spawn role="design-brand-guardian"`), the matching role template seeds the child's identity and knowledge vault.

Roles are namespaced by division: `design-*`, `engineering-*`, `marketing-*`, `product-*`, `project-management-*`, `support-*`, `testing-*`, `specialized-*`, `spatial-*`, `strategy-*`.

## EloPhantoHub — Skill Registry

EloPhantoHub is a GitHub-based skill registry that provides a centralized marketplace for discovering and sharing skills.

### Registry Format

```
elophantohub/
├── index.json          # Master skill index
├── skills/
│   ├── gmail-automation/
│   │   ├── metadata.json
│   │   └── SKILL.md
│   └── docker-management/
│       ├── metadata.json
│       └── SKILL.md
```

### Hub Client

The `HubClient` (`core/hub.py`) handles:

- **Index caching**: Fetches `index.json` from GitHub, caches locally with configurable TTL (default 6 hours)
- **Search**: Keyword matching against skill names, descriptions, and tags with relevance scoring
- **Install**: Downloads `SKILL.md` and `metadata.json` to the local `skills/` directory
- **Update**: Checks for newer versions of hub-installed skills
- **Manifest tracking**: Maintains `installed.json` to track which skills came from the hub

### Agent Auto-Discovery

The agent has access to `hub_search` and `hub_install` tools. During planning, if no local skill matches the task, the agent can search EloPhantoHub and install a relevant skill before proceeding.

### Configuration

```yaml
hub:
  enabled: true
  index_url: "https://raw.githubusercontent.com/elophanto/elophantohub/main/index.json"
  auto_suggest: true       # Agent can suggest hub skills during planning
  cache_ttl_hours: 6       # How often to refresh the index
```

## Relationship to Knowledge Base

Skills and the knowledge base serve different purposes:

- **Skills**: Task-type-specific best practices. Read at the START of a task to guide approach. Static reference material.
- **Knowledge base**: Accumulated experience and facts. Searched DURING tasks for relevant context. Dynamic, growing over time.

They complement each other: a skill teaches the agent how to do research well, while the knowledge base stores what the agent has researched.
