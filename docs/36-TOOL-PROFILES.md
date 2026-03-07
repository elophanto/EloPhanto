# EloPhanto — Tool Profiles

## Problem

EloPhanto exposes 140+ tools to the LLM. Some providers enforce hard limits on the number of tools per request (e.g. OpenAI caps at 128). Even without a hard cap, sending every tool on every request wastes tokens and dilutes the model's attention — a coding task doesn't need payment tools, and a browser task doesn't need desktop tools.

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
        openai: gpt-5.4
    planning:
      preferred_provider: openai
      tool_profile: full
      models:
        openai: gpt-5.4

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
- **Extensibility** — Adding a new tool only requires declaring its group; profiles auto-include it
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
