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

## Notes
Additional context...
```

The `Description` and `Triggers` sections are parsed automatically by the SkillManager. The rest is read by the agent when the skill is activated.

## How Skills Work

### Discovery

On startup, the `SkillManager` scans the `skills/` directory for subdirectories containing `SKILL.md` files. It parses each file to extract the name, description, and triggers.

### System Prompt Integration

All discovered skills are listed in the system prompt under `<available_skills>`:

```xml
<available_skills>
<skill>
<name>browser-automation</name>
<description>Best practices for reliable browser automation...</description>
<location>skills/browser-automation/SKILL.md</location>
</skill>
...
</available_skills>
```

The system prompt also includes a `<skill_protocol>` section that instructs the agent to check for matching skills before starting any task.

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

EloPhanto ships with 27 skills across three categories:

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
