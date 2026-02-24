# Swarm Orchestration

## Description
Best practices for spawning, monitoring, and managing external coding agents
(Claude Code, Codex, Gemini CLI) through conversation.

## Triggers
- swarm
- spawn
- agent
- delegate
- parallel
- coding agent
- claude code
- codex
- gemini cli

## Instructions

### When to Spawn Agents
1. **Independent coding tasks** — features, bug fixes, refactors that can be
   described as self-contained assignments with clear acceptance criteria
2. **Parallel work** — multiple tasks that don't depend on each other
3. **Tasks the user wants to delegate** — "have an agent work on X"

### When NOT to Spawn
- Tasks you can do directly with your tools in < 5 steps
- Tasks requiring real-time user interaction or browser access
- Tasks that depend on another agent's output (wait for the first to finish)

### Writing Good Task Descriptions
The task description is the most important input. A good task:
- States the **what** clearly: "Add pagination to the /api/users endpoint"
- Includes **acceptance criteria**: "Must pass existing tests, add new test for page_size param"
- References **specific files** when possible: "Modify src/routes/users.ts and src/tests/users.test.ts"
- Mentions **constraints**: "Do not change the database schema"

Bad: "Fix the API"
Good: "Fix the 500 error on GET /api/users when page > total_pages. Return empty array instead. Add test case."

### Profile Selection
- Let EloPhanto auto-select unless you have a strong preference
- Auto-selection uses keyword matching against profile `strengths`
- Override with `profile` param when you know which agent is best

### Monitoring Strategy
- Use `swarm_status` to check on agents periodically
- The background monitor handles routine checks (tmux alive, PR created, CI status)
- Check manually when the user asks "how are my agents doing?"

### Redirection
- Use `swarm_redirect` early — don't wait for the agent to go far off track
- Be specific: "Use the existing ConfigSnapshot type from src/types/config.ts"
- Don't redirect for style preferences — save it for the code review

### Anti-Patterns
- **Too many agents at once** — respect max_concurrent_agents, each needs ~3GB RAM
- **Vague tasks** — "improve the codebase" will waste time and tokens
- **Micro-managing** — don't redirect every 2 minutes, let agents work
- **Ignoring failures** — if an agent fails, read the reason before respawning
- **Skipping review** — always review PRs before merging, even if CI passes
