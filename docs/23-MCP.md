# EloPhanto — MCP Integration

## Overview

EloPhanto natively supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) as a client. This lets the agent connect to external MCP servers and use their tools alongside built-in tools — the LLM sees no difference between a built-in tool and one from an MCP server.

Instead of building a custom plugin for every service, you can point EloPhanto at any MCP server (filesystem, GitHub, databases, Slack, Notion, etc.) and its tools appear automatically.

Browse available servers at [mcpservers.org](https://mcpservers.org/).

## Quick Start

The easiest way to set up MCP is through conversation — just ask the agent:

> "I want to connect to my filesystem via MCP"

The agent will guide you through the setup: install the SDK if needed, add the server to config, store secrets in the vault, and test the connection — all without leaving the chat.

### Alternative: Manual Setup

1. Add a server to `config.yaml`:

```yaml
mcp:
  enabled: true
  servers:
    filesystem:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/documents"]
```

2. Start EloPhanto — the MCP SDK is auto-installed on first use, and the filesystem tools appear alongside built-in tools.

### Alternative: Init Wizard

```bash
elophanto init          # Step 8 covers MCP setup with presets
elophanto init edit mcp # Edit just the MCP section
```

### Alternative: CLI Management

```bash
elophanto mcp list            # Show configured servers
elophanto mcp add github      # Add a server interactively
elophanto mcp remove github   # Remove a server
elophanto mcp test            # Test all connections
elophanto mcp test github     # Test a specific server
```

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                      EloPhanto Agent                            │
├─────────────────────────────────────────────────────────────────┤
│                       Tool Registry                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────────────────┐│
│  │ Built-in │ │ Plugins  │ │ MCP Tools (auto-discovered)      ││
│  │ (95+)    │ │          │ │ mcp_filesystem_read_file         ││
│  │          │ │          │ │ mcp_github_create_issue          ││
│  │          │ │          │ │ mcp_postgres_query               ││
│  └──────────┘ └──────────┘ └──────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│                    MCPClientManager                             │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────────────┐ │
│  │ filesystem    │ │ github        │ │ postgres              │ │
│  │ (stdio)       │ │ (stdio)       │ │ (HTTP)                │ │
│  │ npx → child   │ │ npx → child   │ │ https://mcp.co/db    │ │
│  └───────┬───────┘ └───────┬───────┘ └───────────┬───────────┘ │
│          │                 │                     │              │
│     JSON-RPC 2.0     JSON-RPC 2.0          JSON-RPC 2.0       │
│     (stdin/stdout)   (stdin/stdout)        (Streamable HTTP)   │
└──────────┼─────────────────┼─────────────────────┼──────────────┘
           ▼                 ▼                     ▼
    ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐
    │ MCP Server   │  │ MCP Server   │  │ MCP Server         │
    │ (subprocess) │  │ (subprocess) │  │ (remote)           │
    └──────────────┘  └──────────────┘  └────────────────────┘
```

### Lifecycle

1. **Startup**: `MCPClientManager` connects to all enabled MCP servers concurrently
2. **Discovery**: Each connection calls `tools/list` to discover available tools
3. **Registration**: Each MCP tool is wrapped as an `MCPTool` (extends `BaseTool`) and registered in the standard `ToolRegistry`
4. **Operation**: LLM calls MCP tools via the normal executor pipeline — same permissions, same approval flow
5. **Shutdown**: All MCP sessions and subprocesses are cleanly terminated

### Protocol

MCP uses [JSON-RPC 2.0](https://www.jsonrpc.org/specification) with these key methods:

| Method | Direction | Purpose |
|--------|-----------|---------|
| `initialize` | Client → Server | Handshake + capability negotiation |
| `tools/list` | Client → Server | Discover available tools |
| `tools/call` | Client → Server | Execute a tool with arguments |
| `notifications/tools/list_changed` | Server → Client | Tool list updated |

## Configuration

### Full Config Reference

```yaml
mcp:
  enabled: true                          # Master switch for MCP support
  servers:
    # Each key is the server name (used in tool namespacing)

    filesystem:                          # Stdio server (local subprocess)
      command: npx                       # Executable to run
      args:                              # Arguments passed to the command
        - "-y"
        - "@modelcontextprotocol/server-filesystem"
        - "/Users/me/documents"
        - "/Users/me/downloads"
      env: {}                            # Environment variables (optional)
      cwd: ""                            # Working directory (optional)
      permission_level: moderate         # Default for all tools from this server
      timeout_seconds: 30                # Per-tool-call timeout
      startup_timeout_seconds: 30        # Connection handshake timeout
      enabled: true                      # Per-server toggle

    github:                              # Stdio server with vault-referenced secrets
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "vault:github_token"

    postgres:                            # HTTP server (remote)
      url: "https://mcp.company.com/db"  # Server URL (presence auto-detects HTTP)
      headers:                           # HTTP headers (optional)
        Authorization: "vault:mcp_db_auth"
      permission_level: destructive      # Override: DB writes are destructive
      timeout_seconds: 60                # Longer timeout for queries
```

### Transport Auto-Detection

You don't need to specify the transport type explicitly:

- If `url` is present → **Streamable HTTP** transport
- If `command` is present → **stdio** transport (subprocess)
- Explicit `transport: stdio` or `transport: http` overrides auto-detection

### Vault References

Environment variables and HTTP headers support `vault:key_name` references. These are resolved at connection time using EloPhanto's encrypted vault:

```yaml
env:
  API_KEY: "vault:my_api_key"       # Resolved from vault
  STATIC_VAR: "plain-text-value"    # Used as-is
```

Store secrets with: `elophanto vault set my_api_key sk-abc123`

If the vault key is not found or the vault is locked, a warning is logged and the variable is omitted. The MCP server may still start (if the key is optional) or fail on its own (if required).

## Supported Transports

### Stdio (Local Subprocess)

The agent spawns the MCP server as a child process and communicates via stdin/stdout using JSON-RPC 2.0 messages.

**Best for**: Local tools that need filesystem access, CLI wrappers, tools that run on your machine.

**How it works**:
1. Agent runs the `command` with `args` as a subprocess
2. Sends JSON-RPC messages to the process's stdin
3. Reads JSON-RPC responses from the process's stdout
4. Process is killed on agent shutdown

**Requirements**: The command must be installed and available in PATH (e.g., `npx`, `uvx`, `python`).

### Streamable HTTP (Remote)

The agent connects to a remote MCP server over HTTP. Messages are sent as HTTP POST requests with JSON-RPC bodies. Server can optionally use SSE for streaming responses.

**Best for**: Shared team servers, cloud-hosted services, databases, APIs that run elsewhere.

**How it works**:
1. Agent sends HTTP POST requests to the server URL
2. Each request contains a JSON-RPC message
3. Server responds with JSON-RPC response (or SSE stream)
4. Connection closed on agent shutdown

## Tool Namespacing

MCP tools are namespaced to avoid collisions with built-in tools:

```
mcp_{server_name}_{tool_name}
```

Examples:
- `filesystem` server's `read_file` → `mcp_filesystem_read_file`
- `github` server's `create_issue` → `mcp_github_create_issue`
- `postgres` server's `query` → `mcp_postgres_query`

Server names are sanitized: only `a-z`, `0-9`, `_` allowed (other characters replaced with `_`).

Tool descriptions are prefixed with `[MCP:server_name]` so the LLM can identify tool provenance:

```
[MCP:filesystem] Read the contents of a file at the specified path
```

## Permission Levels

All MCP tools go through EloPhanto's standard permission system. The permission level is configurable per-server:

| Level | Behavior | Use Case |
|-------|----------|----------|
| `safe` | Auto-approved | Read-only MCP servers (filesystem read, search) |
| `moderate` | Asks in `ask_always` and `smart_auto` modes | **Default** — most MCP servers |
| `destructive` | Always asks unless `full_auto` | Servers that write data (DB, GitHub) |
| `critical` | Always asks | Servers with irreversible actions |

Example:

```yaml
servers:
  search:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-brave-search"]
    permission_level: safe          # Read-only search, auto-approve

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    permission_level: destructive   # Can create issues, PRs, etc.
```

Per-tool overrides are also possible via `permissions.yaml`:

```yaml
tool_overrides:
  mcp_github_search_repositories: "auto"  # Auto-approve this specific tool
  mcp_github_create_issue: "ask"          # Always ask for this one
```

## Agent Self-Management

The agent can fully manage MCP through conversation using the built-in `mcp_manage` tool:

| Action | What it does |
|--------|-------------|
| `list` | Show all configured MCP servers and SDK status |
| `add` | Add a new server to config.yaml (stdio or HTTP transport) |
| `remove` | Remove a server from config.yaml |
| `test` | Connect to server(s), discover tools, show results |
| `install` | Install the MCP SDK (`mcp[cli]>=1.0.0`) |

The agent also uses `vault_set` to store secrets (API keys, tokens) referenced via `vault:key_name` in config.

### System Prompt Integration

When MCP is **not configured**, the agent's system prompt includes setup guidance — it knows about common MCP servers and can walk the user through configuration.

When MCP **is configured**, the system prompt tells the agent about its available MCP tools and how to manage servers via `mcp_manage`.

This follows the same pattern as email and payments setup.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| MCP SDK not installed | Auto-installed on agent startup if `mcp.enabled: true` |
| SDK auto-install fails | Warning logged with manual install instructions, MCP disabled |
| Server fails to start | Warning logged, other servers continue normally |
| Server crashes during operation | Tool calls return `ToolResult(success=False)` with error message |
| Tool call times out | Returns error after `timeout_seconds` (default 30s) |
| Vault key not found | Warning logged, env var/header omitted |
| Server returns `isError: true` | Mapped to `ToolResult(success=False, error=...)` |

Failed MCP servers never block agent startup. The agent continues with whatever tools are available.

## Popular MCP Servers

Some well-known MCP servers you can use with EloPhanto:

### Filesystem

```yaml
filesystem:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allow"]
```

Read, write, move, search files in specified directories.

### GitHub

```yaml
github:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-github"]
  env:
    GITHUB_PERSONAL_ACCESS_TOKEN: "vault:github_token"
  permission_level: destructive
```

Create issues, PRs, search repos, manage branches.

### Brave Search

```yaml
brave-search:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-brave-search"]
  env:
    BRAVE_API_KEY: "vault:brave_api_key"
  permission_level: safe
```

Web search via Brave Search API.

### PostgreSQL

```yaml
postgres:
  command: npx
  args:
    - "-y"
    - "@modelcontextprotocol/server-postgres"
    - "postgresql://user:pass@localhost:5432/mydb"
  permission_level: destructive
```

Query and modify PostgreSQL databases.

### Playwright (Browser)

```yaml
playwright:
  command: npx
  args: ["-y", "@anthropic/mcp-server-playwright"]
```

Browser automation (alternative to EloPhanto's built-in browser bridge).

### Slack

```yaml
slack:
  command: npx
  args: ["-y", "@anthropic/mcp-server-slack"]
  env:
    SLACK_BOT_TOKEN: "vault:slack_bot_token"
    SLACK_TEAM_ID: "T12345678"
  permission_level: moderate
```

Read channels, post messages, search Slack workspace.

Browse more at [mcpservers.org](https://mcpservers.org/) and the [official MCP servers repo](https://github.com/modelcontextprotocol/servers).

## Result Mapping

MCP tool results are converted to EloPhanto's `ToolResult` format:

| MCP Content | EloPhanto ToolResult |
|-------------|---------------------|
| Single text | `data={"output": "text content"}` |
| Multiple text items | `data={"output": [{"type": "text", "content": "..."}]}` |
| Image | `data={"type": "image", "mimeType": "image/png", "size": 1234}` |
| Resource | `data={"type": "resource", "uri": "file:///...", "text": "..."}` |
| Error (`isError: true`) | `success=False, error="error text"` |

## Limitations

- **Tools only** — MCP resources and prompts are not currently consumed (tools are the primary use case)
- **No parallel execution** — MCP tools are not in the `_PARALLEL_SAFE_TOOLS` set (conservative default for external tools)
- **Binary data** — Image and audio content is referenced as metadata, not passed as raw bytes
- **No tool list change notifications** — Tool list is discovered once at startup; restart to pick up changes

## Dependencies

The MCP SDK (`mcp[cli]>=1.0.0`) is handled automatically:

- **setup.sh** installs it as part of the standard setup (`uv pip install -e '.[mcp]'`)
- **Agent startup** auto-installs it if `mcp.enabled: true` but the package is missing (useful for existing installs that pre-date MCP support)
- **`mcp_manage install`** — the agent can install the SDK through conversation

Manual install is also possible:

```bash
uv pip install "mcp[cli]"
# or
uv pip install -e ".[mcp]"
```

## CLI Reference

### `elophanto mcp list`

Shows all configured MCP servers with transport type, command/URL, permission level, and enabled status.

### `elophanto mcp add NAME`

Interactive wizard to add a new MCP server:
- Transport type (stdio or HTTP)
- Command and arguments (stdio) or URL (HTTP)
- Environment variables with vault reference support
- Permission level (safe, moderate, destructive)
- Auto-enables MCP in config
- Offers to test the connection immediately

### `elophanto mcp remove NAME`

Removes a server from config with confirmation prompt.

### `elophanto mcp test [NAME]`

Connects to one or all servers, runs tool discovery, and displays the list of available tools. Requires the MCP SDK — if not installed, prints the install command.

### `elophanto init` (Step 8)

The init wizard includes MCP configuration as step 8:
- Presets for common servers (filesystem, GitHub, Brave Search)
- Custom server setup with full transport/env/permission options
- Add multiple servers in a loop
- Also accessible via `elophanto init edit mcp`
