# EloPhanto — Tool Profiles

> **Status: shipped.** The design below was a proposal; it is now the live
> mechanism in `core/tool_profiles.py`. The tables in the proposal sections
> are kept for the reasoning, but they no longer list every group — treat
> `DEFAULT_PROFILES` as the source of truth and the "Reachability" section
> immediately below as the operational rule.

## Reachability — the trap this doc got wrong

An earlier version of this document claimed:

> Adding a new tool only requires declaring its group; profiles auto-include it.

**That is false, and believing it has broken shipped features five times.**
A PROFILE-tier tool reaches the LLM only when its `group` appears in the
active profile's `allowed_groups`. Declaring a group does nothing on its own.
Registering a tool and exposing it are separate steps, and nothing in the type
system ties them together.

The failure is silent and convincing: the tool imports, registers, passes its
unit tests (which instantiate it directly and never touch profile filtering),
appears in `capabilities.md`, and is simply never offered to the model. It
looks exactly like a working feature until someone reads a live log and
notices it is never called.

Casualties before the guard existed: the ABE management tools, missions,
prospecting, watch, then the entire action layer (`http_request`, `gmail`,
`node_*`, `panel_*`), and 33 tools across `ambient` (the whole anticipation
organ), `polymarket`, `solana`, `jobs` and `affect`.

`tests/test_core/test_tool_profiles_coverage.py` now fails when:

- a PROFILE-tier group is missing from `full`,
- a profile names a group no tool declares,
- a key tool drops out of the `planning` surface,
- or `planning` grows past the provider-cap ceiling.

**When you add a tool:** put its group in `full` (that is what makes it
reachable at all), and in `planning` if the agent loop should reach it by
default. `full` is the superset; `planning` is what the loop and the
autonomous mind actually run under, so `full`-only means "reachable via
tool_discover or an explicit profile", not "working".

## Live profiles

| Profile | Used for | Tools |
|---|---|---|
| `minimal` | `analysis`, `simple` task types | ~30 |
| `coding` | code generation and review | 39 |
| `browsing` | web research | — |
| `research` | competitor analysis, market scans | 86 |
| `planning` | **the agent loop and the autonomous mind** | 202 |
| `full` | default fallback; the superset | 252 |

`planning` is deliberately thinner than `full` — the prompt diet keeps
desktop, swarm, org, mcp, social, media and payments out of it. Those stay
reachable through `tool_discover`. `test_prompt_diet.py` pins that split, so
widening it is a deliberate act rather than a drive-by.


## Problem

EloPhanto exposes 287 tools to the LLM. Some providers enforce hard limits on the number of tools per request (e.g. OpenAI caps at 128). Even without a hard cap, sending every tool on every request wastes tokens and dilutes the model's attention — a coding task doesn't need payment tools, and a browser task doesn't need desktop tools.

## Current Approach: Priority-Based Trimming

The router currently uses `_trim_tools_for_limit()` in `core/router.py` to drop low-priority tools when a provider limit is hit. Tools are split into two tiers:

**Core** (always kept):
- System tools (`shell_execute`, `file_read`, `file_write`, `file_list`, etc.)
- Browser tools (`browser_navigate`, `browser_read_page`, etc.)
- Knowledge tools (`knowledge_search`, `knowledge_write`, etc.)
- Goal tools (`goal_create`, `goal_status`, `goal_manage`)
- Skill tools (`skill_read`, `skill_list`)
- Data tools (`db_query`, `db_write`, `llm_call`)
- Self-dev tools (`self_read_source`, `self_modify_source`, etc.)
- Scheduling tools (`schedule_task`, `schedule_list`)
- Mind tools (`set_next_wakeup`, `update_scratchpad`)
- Document tools (`document_analyze`, `document_query`, etc.)
- Email tools (`email_send`, `email_read`, etc.)
- Payment tools (`wallet_balance`, `send_payment`, etc.)
- Swarm tools (`swarm_spawn`, `swarm_status`, etc.)

**Low priority** (dropped first when over limit):
- MCP tools (`mcp__*`) — often duplicate built-in file/search tools
- Commune tools (`commune_*`) — social network, not essential for task execution
- Replicate tools (`replicate_*`) — image generation plugin
- Deployment tools (`deploy_*`, `deployment_*`) — cloud provisioning
- Desktop tools (`desktop_*`) — GUI control, rarely needed alongside other tools
- Organization tools (`organization_*`) — self-cloning
- TOTP tools (`totp_*`) — authenticator codes
- Database provisioning (`create_database`)

This works as a stopgap but has limitations: the priority split is static, and tools that are irrelevant to the current task still consume token budget.

## Proposed: Context-Aware Tool Profiles

### Design

Instead of sending all tools and trimming at the edge, select tools **before** the LLM call based on the task context. Each tool declares which **profiles** and **groups** it belongs to. The router activates the right profile based on the task.

### Tool Groups

Semantic categories for tool organization:

| Group | Tools | Description |
|-------|-------|-------------|
| `system` | `shell_execute`, `file_read`, `file_write`, `file_list`, `file_delete`, `file_move`, `vault_set` | Core system operations |
| `browser` | `browser_connect`, `browser_navigate`, `browser_read_page`, `browser_interact`, `browser_tabs`, `browser_cookies`, `browser_download`, `browser_screenshot` | Web browser control |
| `desktop` | `desktop_screenshot`, `desktop_click`, `desktop_type`, `desktop_key`, `desktop_scroll`, `desktop_move` | Desktop GUI automation |
| `knowledge` | `knowledge_search`, `knowledge_write`, `knowledge_index` | Knowledge base operations |
| `data` | `db_query`, `db_write`, `llm_call` | Database and LLM access |
| `selfdev` | `self_read_source`, `self_modify_source`, `self_create_plugin`, `self_list_capabilities`, `self_run_tests`, `self_rollback` | Self-development pipeline |
| `goals` | `goal_create`, `goal_status`, `goal_manage` | Long-running goal management |
| `skills` | `skill_read`, `skill_list` | Skill discovery and reading |
| `scheduling` | `schedule_task`, `schedule_list` | Task scheduling |
| `mind` | `set_next_wakeup`, `update_scratchpad` | Autonomous mind operations |
| `documents` | `document_analyze`, `document_query`, `document_collections` | Document processing |
| `comms` | `email_send`, `email_read`, `email_list` | Email communication |
| `payments` | `wallet_balance`, `send_payment`, `payment_history` | Financial transactions |
| `identity` | `totp_enroll`, `totp_generate`, `totp_list`, `totp_delete` | Identity and authentication |
| `media` | `replicate_generate` | Image/media generation |
| `social` | `commune_*` | Agent social platform |
| `infra` | `deploy_*`, `deployment_*`, `create_database` | Infrastructure management |
| `org` | `organization_*` | Agent organization/cloning |
| `swarm` | `swarm_spawn`, `swarm_status` | Agent swarm orchestration |
| `mcp` | `mcp__*`, `mcp_manage` | External MCP server tools |

### Profiles

Predefined tool sets for common task types. Each profile includes a base set of groups:

| Profile | Groups Included | Typical Use |
|---------|----------------|-------------|
| `minimal` | `system`, `knowledge`, `data`, `skills` | Simple tasks, formatting, classification |
| `coding` | `system`, `knowledge`, `data`, `skills`, `selfdev`, `goals` | Code generation and review |
| `browsing` | `system`, `knowledge`, `data`, `skills`, `browser` | Web research and interaction |
| `desktop` | `system`, `knowledge`, `data`, `skills`, `desktop` | GUI automation tasks |
| `comms` | `system`, `knowledge`, `data`, `skills`, `comms`, `identity` | Email and messaging |
| `devops` | `system`, `knowledge`, `data`, `skills`, `infra`, `swarm` | Deployment and infrastructure |
| `full` | All groups | General-purpose, planning, autonomous mind |

### Profile Selection

The router selects a profile based on the task context:

```
1. Explicit override — caller specifies a profile
2. Task-type mapping:
   - planning     → full
   - coding       → coding
   - analysis     → minimal + documents
   - simple       → minimal
3. Autonomous mind → full (needs access to everything)
4. Goal execution  → full (goals can involve any tool)
5. Default         → full
```

### Tool Declaration

Each tool class declares its group membership via a `group` attribute on `BaseTool`:

```python
class ShellExecute(BaseTool):
    name = "shell_execute"
    group = "system"
    # ...
```

MCP tools inherit group `mcp` automatically. Plugin tools inherit group based on their `schema.json` or default to `system`.

### Provider-Level Policies

Different providers can have different tool policies layered on top of profiles:

```yaml
llm:
  routing:
    coding:
      preferred_provider: openai
      tool_profile: coding          # profile for this task type
      models:
        openai: gpt-5.5
    planning:
      preferred_provider: openai
      tool_profile: full
      models:
        openai: gpt-5.5

  providers:
    openai:
      max_tools: 128               # hard limit
      tool_deny:                    # always exclude for this provider
        - mcp
        - social
```

The router applies these in order:
1. Select profile for the task type
2. Expand profile into tool groups
3. Collect all tools in those groups
4. Apply provider-level deny list
5. If still over `max_tools`, apply priority-based trimming as fallback

### Benefits

- **Token efficiency** — Models see only relevant tools, improving response quality
- **Provider compatibility** — Stays under provider-specific limits without blind truncation
- **Extensibility** — Adding a new tool requires declaring its group AND adding that group to the profiles that should offer it. Profiles do NOT auto-include new groups; see "Reachability" above.
- **Transparency** — Logs show which profile was activated and how many tools were sent

### Migration Path

1. **Phase 1** (current): Static priority-based trimming in `_trim_tools_for_limit()`. Works today.
2. **Phase 2**: Add `group` attribute to `BaseTool`. Define profile-to-groups mapping. Router selects profile from task type. Falls back to `_trim_tools_for_limit()` if still over limit.
3. **Phase 3**: Add `tool_profile` to routing config. Add `tool_deny` / `tool_allow` to provider config. Full policy pipeline.

## Configuration Reference

```yaml
llm:
  tool_profiles:
    minimal:
      groups: [system, knowledge, data, skills]
    coding:
      groups: [system, knowledge, data, skills, selfdev, goals]
    browsing:
      groups: [system, knowledge, data, skills, browser]
    desktop:
      groups: [system, knowledge, data, skills, desktop]
    comms:
      groups: [system, knowledge, data, skills, comms, identity]
    devops:
      groups: [system, knowledge, data, skills, infra, swarm]
    full:
      groups: [system, knowledge, data, skills, selfdev, goals, browser,
               desktop, documents, comms, payments, identity, media,
               social, infra, org, swarm, mcp, scheduling, mind]

  routing:
    planning:
      tool_profile: full
    coding:
      tool_profile: coding
    analysis:
      tool_profile: minimal
    simple:
      tool_profile: minimal

  providers:
    openai:
      max_tools: 128
      tool_deny: [mcp, social]
    openrouter:
      max_tools: 0                 # 0 = no limit
    zai:
      max_tools: 0
    ollama:
      max_tools: 0
```
