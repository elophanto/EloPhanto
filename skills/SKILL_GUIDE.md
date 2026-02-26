# EloPhanto Skills — Author Guide

Skills are best-practice guides that teach EloPhanto **how** to do specific types
of work well. When a user asks "build me a website", the agent automatically
matches relevant skills (like `frontend-design`, `ui-ux-pro-max`) and reads
their instructions before starting work.

## How Skills Work

```
User message → match_skills(query) → top 5 recommended → agent reads them → follows instructions
```

1. **Startup**: `SkillManager.discover()` scans `skills/*/SKILL.md`, parses name,
   description, and triggers from each file.
2. **Every message**: The user's goal is matched against all skills using keyword
   scoring (triggers → name → description). Top 5 matches are injected into the
   system prompt as `<recommended>` skills.
3. **Agent reads**: The LLM sees recommended skills and calls `skill_read` to load
   the full SKILL.md content before starting work.
4. **Agent follows**: Instructions from the skill guide the agent's approach
   throughout the task.

## Matching Algorithm

Skills are scored against the user's query using three signal levels:

| Signal | Score | Example |
|--------|-------|---------|
| **Trigger phrase** in query | +3 | trigger "landing page" in "build a landing page" |
| **Trigger word** overlap | +2 | trigger "react" matches query word "react" |
| **Name word** match | +2 | skill `nextjs` matches query "deploy nextjs app" |
| **Name substring** match | +1 | skill `web-*` matches query "website" (web ⊂ website) |
| **Description word** overlap | +1 each | description has "dashboard" matching query |

Stop words (a, the, build, create, help, etc.) are filtered out to prevent
false matches.

**Scaling**: Only the top 5 matched skills get full XML. Non-matching skills
are shown as compact one-liners (max 20), then just a count. This keeps prompt
size bounded at ~5KB regardless of total skill count (tested up to 500+).

## File Structure

```
skills/
├── SKILL_GUIDE.md          ← this file
├── _template/SKILL.md      ← starter template
├── my-skill/
│   └── SKILL.md            ← skill definition
├── another-skill/
│   ├── SKILL.md
│   └── metadata.json       ← optional (for hub-installed skills)
```

Directories starting with `_` or `.` are ignored.

## Writing a SKILL.md

### Minimal Example

```markdown
---
name: my-skill
description: Short one-liner explaining what this skill does.
---

# My Skill

## Triggers

- keyword1
- keyword2
- multi-word phrase

## Instructions

1. Do this first
2. Then do that
3. Verify the result
```

### Full Example

```markdown
---
name: react-dashboard
description: Build production-grade React dashboards with proper state management, data fetching, and responsive layouts.
---

# React Dashboard Builder

## Triggers

- react dashboard
- admin panel
- data table
- chart component
- analytics page
- react admin
- dashboard layout

## When to Apply

Use this skill when the user asks to:
- Build a dashboard or admin panel
- Create data visualization pages
- Design analytics interfaces

## Instructions

1. **Layout first**: Start with a responsive grid layout using CSS Grid or Flexbox.
   Never use fixed widths for the main container.

2. **Data fetching**: Use React Query (TanStack Query) for server state.
   Never fetch data in useEffect directly.

3. **Components**:
   - Use shadcn/ui for base components
   - Charts: recharts or nivo
   - Tables: TanStack Table
   - Forms: react-hook-form + zod

4. **State management**: Local state for UI, React Query for server state.
   Only add Zustand if multiple components need shared client state.

5. **Responsive**: Test at 3 breakpoints minimum (mobile, tablet, desktop).
   Sidebar should collapse on mobile.

## Examples

### Good
- Responsive sidebar with collapsible navigation
- Data table with sorting, filtering, pagination
- Chart cards with loading skeletons

### Bad
- Fixed-width layout that breaks on mobile
- Fetching all data on mount with no pagination
- Inline styles instead of a design system

## Notes

- Always check if the user already has a UI library before suggesting one
- Prefer server components in Next.js App Router for data-heavy pages
```

## Triggers — Best Practices

Triggers are the most important part for matching. Good triggers ensure your
skill gets recommended when relevant.

### Do

- **Include variations**: website, site, web app, webapp, web application
- **Include actions**: build, fix, review, audit, optimize, deploy
- **Include technology names**: react, nextjs, tailwind, prisma
- **Include problem descriptions**: slow animation, accessibility issue, seo
- **Use lowercase**: matching is case-insensitive but keep triggers clean
- **10-20 triggers** is the sweet spot

### Don't

- **Don't use generic words alone**: "code", "help", "app" will match too broadly
- **Don't duplicate other skills' triggers**: if `nextjs` skill owns "next.js",
  don't add it to `react-best-practices`
- **Don't over-trigger**: 50+ triggers dilute relevance — the skill will match
  queries it shouldn't

### Trigger Examples by Skill Type

**Framework skill** (e.g., nextjs):
```
- nextjs
- next.js
- next
- app router
- server component
- ssr
- ssg
- vercel
```

**Task skill** (e.g., fixing-accessibility):
```
- accessibility
- a11y
- aria
- screen reader
- keyboard navigation
- focus
- contrast
- alt text
```

**Design skill** (e.g., ui-ux-pro-max):
```
- ui
- ux
- design
- website
- landing page
- dashboard
- color palette
- typography
- responsive
- dark mode
```

## Two Formats for Metadata

### Format 1: YAML Frontmatter (recommended)

```markdown
---
name: my-skill
description: One-liner shown in skill listings and used for matching.
---
```

### Format 2: Markdown Sections

```markdown
## Description

One-liner shown in skill listings and used for matching.

## Triggers

- keyword1
- keyword2
```

Both formats are parsed automatically. YAML frontmatter is preferred for new
skills since it's more compact and standard.

## Hub Skills

Skills installed from EloPhantoHub include a `metadata.json`:

```json
{
  "source": "elophantohub",
  "author_tier": "verified",
  "installed_at": "2026-02-26T10:00:00Z"
}
```

Hub skills are displayed with their trust tier (new, verified, trusted, official)
and any security warnings detected during content scanning.

## Security

SKILL.md files are scanned for dangerous patterns:

- **Blocked** (skill rejected): curl|bash, reverse shells, credential theft,
  prompt injection, base64 decode, destructive rm -rf
- **Warning** (skill loaded with flag): external URLs, pip/npm install,
  chmod, sudo

See `SKILL_BLOCKED_PATTERNS` and `SKILL_WARNING_PATTERNS` in `core/skills.py`.

## Testing Your Skill

```bash
# Check which skills match a query
python3 -c "
from pathlib import Path
from core.skills import SkillManager
sm = SkillManager(Path('skills'))
sm.discover()
for s in sm.match_skills('your query here', max_results=5):
    print(f'  {s.name} (triggers: {len(s.triggers)})')
"
```
