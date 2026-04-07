# 62 — Agent OS: The Path to the Next Linux

> Making EloPhanto the foundational agent operating system that others
> build on top of — not just another agent framework.

**Status:** In Progress
**Priority:** P0 — Strategic direction

---

## Thesis

Linux won because anyone could build software FOR it. Not because the
kernel was the best — because the ecosystem was open, standardized, and
composable. EloPhanto must become the same for agents: the layer that
others build on top of.

---

## What We Already Have

| Linux Analogy | EloPhanto Equivalent | Status |
|---|---|---|
| Kernel | `core/agent.py` — plan-execute-reflect loop | Done |
| Syscalls | `BaseTool` interface (163+ tools) | Done |
| Users/Groups | Authority tiers (OWNER/TRUSTED/PUBLIC) | Done |
| Package manager | EloPhantoHub + `core/hub.py` (SHA-256, revocation) | Basic |
| Device drivers | LLM providers (6) + MCP servers | Done |
| Init system | Autonomous mind + heartbeat + scheduler | Done |
| Networking | Gateway WebSocket protocol (24+ event types) | Done |
| Process isolation | Session manager (per-user, per-channel) | Done |
| Fork/exec | Swarm (external agents) + Organization (child agents) | Done |
| Machine fingerprint | Census + HMAC-SHA-256 fingerprint | Done |
| Cloud deploy | Dockerfile + fly.toml | Done |

---

## What's Missing

### 1. Agent Protocol Specification (the "POSIX" for agents)

**Problem:** Our gateway protocol works but it's internal. No spec,
no versioning, no way for third-party agents to interoperate.

**Solution:** Publish `AGENT_PROTOCOL.md` as a formal specification.
Version it. Make it the standard for agent-to-agent communication.

**Scope:**
- Message format (JSON, already defined in `core/protocol.py`)
- Authentication (Bearer token, already in gateway)
- Session management (create, resume, end)
- Tool discovery (list available tools with schemas)
- Task delegation (request + response + streaming)
- Event subscription (real-time updates)
- Capability negotiation (what can this agent do?)

**What exists:** `core/protocol.py` (8 message types, 24+ event types),
gateway WebSocket server, channel adapters. Census heartbeat to
`api.elophanto.com`. MCP client for tool interop.

**What to build:**
- `AGENT_PROTOCOL.md` — versioned spec (v1.0)
- `core/protocol.py` — add capability negotiation messages
- `core/gateway.py` — add `/agents/register` and `/agents/discover` HTTP endpoints
- Agent-to-agent task delegation via gateway

### 2. SDK Package (`elophanto-sdk`)

**Problem:** You can't build tools for EloPhanto without forking the
entire repo. There's no `pip install elophanto-sdk`.

**Solution:** Extract `BaseTool`, `ToolResult`, `PermissionLevel`, and
a thin client into a standalone package.

**What to build:**
- `sdk/` directory with `pyproject.toml`
- Exports: `BaseTool`, `ToolResult`, `PermissionLevel`, `ToolTier`
- `EloClient` class — WebSocket client that connects to gateway
- `@tool` decorator for quick tool definition
- `elophanto-sdk` on PyPI

### 3. Distribution Profiles

**Problem:** One-size-fits-all agent. A developer doesn't need affiliate
marketing tools. A marketer doesn't need code execution.

**Solution:** Profile-based configurations that pre-select tools, skills,
and settings for vertical use cases.

**What exists:** Tool profiles (`core/config.py` ToolProfileConfig),
authority tiers, skill matching.

**What to build:**
- `profiles/` directory with YAML configs:
  - `profiles/developer.yaml` — coding tools, git, swarm, TDD skills
  - `profiles/marketer.yaml` — social, publishing, affiliate, analytics
  - `profiles/researcher.yaml` — browser, web search, documents, context store
  - `profiles/finance.yaml` — payments, prospecting, Solana, trading
  - `profiles/minimal.yaml` — core tools only, lightweight
- `elophanto start --profile developer`
- Profile = tool selection + skill selection + config overrides

### 4. Versioned Skill Packages

**Problem:** Skills are flat SKILL.md files with no version, no
dependencies, no lock file. Can't pin `ui-ux-pro-max@2.1.0`.

**What exists:** EloPhantoHub with version field, SHA-256 checksums,
author tiers, revocation. `core/hub.py` client.

**What to build:**
- `skills.lock` — lock file tracking installed skill versions + checksums
- `elophanto skill install name@version` with version resolution
- Skill dependencies: `requires: [skill-a, skill-b]` in frontmatter
- `elophanto skill update` — check for newer versions
- Skill changelog support in hub index

### 5. Agent Mesh (Agent-to-Agent)

**Problem:** Agents can only talk to us (hub-and-spoke). No peer mesh.
Two EloPhanto instances can't collaborate.

**What exists:** Swarm (spawns external CLI agents), Organization
(persistent child agents via ParentChannelAdapter), Agent Commune
(social platform — posts/comments, not task delegation).

**What to build:**
- `core/agent_mesh.py` — peer discovery + task delegation
- Agents register on census with capabilities
- Agent A discovers Agent B via census API
- Task delegation: "I need a video edited" → finds agent with Remotion
  skills → delegates via Agent Protocol
- Result aggregation and payment settlement

### 6. Contributor Ecosystem

**Problem:** CONTRIBUTING.md exists but no governance, no RFC process,
no issue templates, no good-first-issue program.

**What exists:** CONTRIBUTING.md (93 lines), Apache 2.0 license.

**What to build:**
- `.github/ISSUE_TEMPLATE/` — bug report, feature request, skill proposal
- `.github/PULL_REQUEST_TEMPLATE.md`
- `docs/RFC-TEMPLATE.md` — for major architectural changes
- `GOVERNANCE.md` — BDFL model (for now) with pathway to foundation
- Label taxonomy: `good-first-issue`, `skill-wanted`, `rfc`, `breaking`
- `SECURITY.md` — vulnerability reporting process

### 7. Cross-Platform Parity

**Problem:** macOS-primary. Docker exists but no Windows support,
no one-click cloud templates.

**What exists:** Dockerfile + fly.toml, setup.sh (macOS/Linux).

**What to build:**
- Railway template (`railway.json`)
- Render blueprint (`render.yaml`)
- Docker Compose for local multi-service (agent + web dashboard)
- Windows setup script (`setup.ps1`) or WSL guide
- One-click deploy buttons in README

---

## Implementation Priority

| # | Feature | Impact | Effort | Linux Analogy |
|---|---------|--------|--------|---------------|
| 1 | Agent Protocol spec | Highest — network effect | Medium | POSIX |
| 2 | Distribution profiles | High — 10x adoption | Low | Ubuntu/Fedora |
| 3 | SDK package | High — third-party tools | Medium | glibc/headers |
| 4 | Contributor ecosystem | High — community growth | Low | kernel.org |
| 5 | Versioned skill packages | Medium — ecosystem quality | Medium | apt/dpkg |
| 6 | Cross-platform parity | Medium — addressable base | Low | distro ports |
| 7 | Agent mesh | Long-term — agent economy | High | TCP/IP |

---

## Build Order

### Phase 1: Foundation (this sprint)
1. Agent Protocol v1.0 specification
2. Distribution profiles (5 verticals)
3. Contributor ecosystem (.github templates, governance)

### Phase 2: Ecosystem (next sprint)
4. SDK package (pip installable)
5. Versioned skill packages (lock file, deps)
6. Cross-platform (Railway, Docker Compose, Windows)

### Phase 3: Network (future)
7. Agent mesh (peer discovery, task delegation)
