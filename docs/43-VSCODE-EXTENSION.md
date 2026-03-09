# VS Code Extension

## Overview

A VS Code extension that connects to the EloPhanto gateway as another channel
adapter — same as CLI, Telegram, Discord, Slack, and the web dashboard. The
agent behaves identically regardless of which client is connected. Chat from
VS Code, continue on Telegram, see the same conversation everywhere.

The extension is a thin WebSocket client. All intelligence lives in the agent.
The extension only handles IDE-specific presentation: showing responses in a
sidebar chat panel, presenting tool approvals as VS Code notifications, and
injecting IDE context (current file, selection, workspace, diagnostics) into
messages.

## Installation

**Important:** The extension is just a UI client — it does NOT run the agent.
EloPhanto must be running separately in a terminal before the extension can
connect. The extension cannot auto-launch the agent because the vault password
must be entered manually in the terminal on first start.

### Step 1: Start EloPhanto

In a terminal, start the agent with the gateway:

```bash
cd /path/to/EloPhanto
./start.sh          # or ./start.sh --web for web dashboard too
```

The gateway starts on `ws://127.0.0.1:18789`. Keep this terminal running —
the extension connects to it. If the gateway is not running when VS Code
starts, the extension shows a warning: *"EloPhanto gateway is not running.
Start it in a terminal: ./start.sh"*

### Step 2: Install the extension

**From source:**

```bash
cd vscode-extension
npm install
npm run build
npx @vscode/vsce package --no-dependencies
```

Then in VS Code: Extensions panel → `...` menu → **"Install from VSIX..."**
→ select the generated `.vsix` file.

> Note: `code --install-extension` from the terminal may not always register
> correctly. Installing via the VS Code UI ("Install from VSIX...") is more
> reliable.

**From VS Code Marketplace:**

Coming soon. Once published, search "EloPhanto" in the Extensions panel.

### Step 3: Use

1. Make sure EloPhanto is running in a terminal (Step 1)
2. The extension auto-connects on VS Code startup
3. Click the EloPhanto icon in the activity bar (left sidebar) to open chat
4. Start chatting — same agent, same conversation as CLI/Telegram/web

If the gateway is on a different host or port, set `elophanto.gatewayUrl` in
VS Code settings. If the extension shows "Disconnected", EloPhanto is not
running — start it in a terminal first.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  VS Code Extension                                    │
│                                                       │
│  ┌─────────────┐  ┌────────────┐  ┌───────────────┐ │
│  │ Chat Panel   │  │ Status Bar │  │ Diff Provider │ │
│  │ (Webview)    │  │ Item       │  │               │ │
│  └──────┬───────┘  └─────┬──────┘  └──────┬────────┘ │
│         │                │                │           │
│  ┌──────┴────────────────┴────────────────┴────────┐ │
│  │           Gateway Client (WebSocket)             │ │
│  │         ws://127.0.0.1:18789                     │ │
│  └──────────────────────┬──────────────────────────┘ │
└─────────────────────────┼────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │    EloPhanto Gateway   │
              │    (shared session)    │
              └───────────────────────┘
```

The extension connects to the same gateway that all other channels use.
When `gateway.unified_sessions: true` (default), every channel shares one
conversation. Messages sent from VS Code appear in CLI, Telegram, and
the web dashboard — and vice versa.

## Components

### 1. Gateway Client

WebSocket client that implements the gateway protocol. Same message types
as all other adapters:

**Client → Gateway:**
- `chat` — send user message (with optional IDE context)
- `approval_response` — approve or deny a tool call
- `command` — send slash commands (`clear`, `stop`, `mind`, etc.)

**Gateway → Client:**
- `response` — agent's reply (may stream via multiple messages with `done: false`)
- `approval_request` — tool needs approval (tool name, description, params)
- `event` — broadcasts (goal progress, mind wakeup, swarm status, etc.)
- `error` — error messages

The client auto-reconnects on disconnect (exponential backoff), queues
messages during disconnection, and sends periodic heartbeats.

### 2. Chat Panel (Sidebar Webview)

A sidebar panel for conversing with the agent. Renders:
- User messages and agent responses with streaming cursor
- Tool execution steps (auto-removed when response arrives)
- Goal progress and mind status events
- Chat history panel (load past conversations from the gateway)
- New Chat button (clears UI only — does NOT wipe agent memory)
- Close button to collapse the sidebar panel

Design matches the web dashboard aesthetic: monospace labels, crop marks
on complete messages, slide-up animations, pulse-dot connection status.

**Important:** There is deliberately NO "clear memory" button. The gateway's
`clear` command is destructive — it wipes all agent memories. This must
never be exposed as a casual UI button.

### 3. IDE Context Injection

The key differentiator from other channels. Every chat message can include
IDE context that the agent uses to understand what the user is working on:

```json
{
  "type": "chat",
  "data": {
    "content": "fix this function",
    "ide_context": {
      "active_file": "src/utils/parser.ts",
      "selection": {
        "text": "function parseDate(input: string) { ... }",
        "start_line": 42,
        "end_line": 58
      },
      "workspace_root": "/Users/alice/projects/my-app",
      "open_files": ["src/utils/parser.ts", "src/index.ts"],
      "language": "typescript",
      "diagnostics": [
        {
          "file": "src/utils/parser.ts",
          "line": 47,
          "severity": "error",
          "message": "Type 'string' is not assignable to type 'Date'"
        }
      ]
    }
  }
}
```

The gateway passes `ide_context` through to the agent, which uses it to:
- Know which file the user is looking at
- See the selected code without the user copy-pasting
- See TypeScript/ESLint errors from the editor
- Understand the workspace structure

### 4. Launcher (Gateway Checker)

On activation, the extension checks if the gateway is reachable via a TCP
socket probe. If not running, it shows a warning message telling the user
to start EloPhanto in a terminal (`./start.sh`).

The extension does **NOT** auto-launch the gateway. The vault password must
be entered manually in the terminal on first start, making auto-launch
impossible from the extension.

### 5. Status Bar

A status bar item showing:
- Connection status (connected/disconnected/reconnecting)
- Agent status (idle/thinking/executing tool)
- Active goal name and progress (if any)
- Mind status (awake/sleeping/paused)
- Click to open the chat panel

### 6. Tool Approval UI

When the agent requests approval for a tool call, the extension shows
a VS Code notification with:
- Tool name and description
- Parameters (formatted, not raw JSON)
- Approve / Deny buttons
- Risk level coloring (green for read-only, yellow for writes, red for destructive)

Same approval flow as all other channels — approve from VS Code or
from Telegram, whichever you see first.

## Gateway Protocol

The extension uses the exact same protocol as all other channels.
No gateway changes needed.

| Message Type | Direction | Purpose |
|---|---|---|
| `chat` | Client → Gateway | User message with optional `ide_context` |
| `response` | Gateway → Client | Agent reply (streaming: `done: false` until final) |
| `approval_request` | Gateway → Client | Tool needs user approval |
| `approval_response` | Client → Gateway | User approves/denies tool |
| `event` | Gateway → Client | Broadcasts (goals, mind, swarm, org) |
| `command` | Client → Gateway | Slash commands (`clear`, `stop`, `mind`, etc.) |
| `status` | Bidirectional | Connection status, heartbeat |
| `error` | Gateway → Client | Error messages |

The only extension to the protocol is the optional `ide_context` field in
chat messages. The gateway passes it through as-is — it doesn't parse or
validate it. The agent's planner reads it from the message data.

## VS Code API Usage

| VS Code API | Used For |
|---|---|
| `vscode.window.registerWebviewViewProvider` | Chat sidebar panel |
| `vscode.window.createStatusBarItem` | Connection + agent status |
| `vscode.window.showInformationMessage` | Tool approval notifications |
| `vscode.workspace.onDidChangeTextDocument` | Track active file changes |
| `vscode.window.onDidChangeActiveTextEditor` | Track current file |
| `vscode.window.onDidChangeTextEditorSelection` | Track selection |
| `vscode.commands.registerCommand` | Extension commands |
| `vscode.languages.getDiagnostics` | Get editor errors/warnings |
| `vscode.diff` | Show proposed changes as diff |

## Commands

| Command | Description |
|---|---|
| `elophanto.connect` | Connect to the gateway |
| `elophanto.disconnect` | Disconnect from the gateway |
| `elophanto.sendSelection` | Send selected code to the agent with context |
| `elophanto.explain` | "Explain this code" with current selection |
| `elophanto.fix` | "Fix this code" with current selection + diagnostics |
| `elophanto.newChat` | Start a new chat (clears UI only, does NOT wipe memory) |
| `elophanto.stop` | Cancel current task |
| `elophanto.mind` | Show autonomous mind status |

Right-click context menu items (when text is selected): Send Selection,
Explain This Code, Fix This Code.

## Configuration

Extension settings in VS Code's `settings.json`:

```json
{
  "elophanto.gatewayUrl": "ws://127.0.0.1:18789",
  "elophanto.autoConnect": true,
  "elophanto.showMindEvents": true,
  "elophanto.showToolSteps": true,
  "elophanto.projectDir": ""
}
```

No EloPhanto-side configuration needed. The gateway already accepts any
WebSocket client. The extension is just another channel.

## Project Structure

```
vscode-extension/
├── package.json              # Extension manifest, commands, views, config
├── tsconfig.json
├── icon.png                  # Extension icon
├── LICENSE
├── dist/                     # esbuild output (single-file bundle)
│   └── extension.js
├── src/
│   ├── extension.ts          # Activation, command registration, wiring
│   ├── gateway-client.ts     # WebSocket client (ws package, auto-reconnect)
│   ├── protocol.ts           # Message types (mirrors core/protocol.py)
│   ├── chat-provider.ts      # WebviewViewProvider — full chat UI inline
│   ├── status-bar.ts         # Status bar item (connected/thinking/etc.)
│   ├── approval.ts           # Tool approval via VS Code notifications
│   ├── launcher.ts           # Gateway checker (TCP probe, no auto-launch)
│   └── context.ts            # IDE context collection (file, selection, diagnostics)
└── elophanto-*.vsix          # Packaged extension (generated)
```

## Implementation Notes

### What was reused from the web dashboard

- **Gateway client pattern** — `gateway-client.ts` mirrors `web/src/lib/gateway.ts`
  (WebSocket with auto-reconnect, message queuing, heartbeat), adapted for
  Node.js `ws` package instead of browser WebSocket.
- **Protocol** — `protocol.ts` mirrors `core/protocol.py` message types. Uses
  `crypto.randomUUID()` (Node.js) instead of browser `crypto`.
- **Chat UI design** — Monospace labels, crop marks, streaming cursor, pulse-dot
  status, slide-up animations — same visual language as the web dashboard.

### What's VS Code-specific

- IDE context collection (`vscode.window.activeTextEditor`, `tabGroups`, diagnostics)
- Tool approval via native VS Code notifications (risk-colored: warning for
  high-risk tools like `shell_execute`, `crypto_transfer`; info for others)
- Status bar integration (connected/disconnected/thinking states)
- Gateway checker via TCP socket probe (no auto-launch)
- esbuild single-file bundle for fast extension loading

### Gateway changes needed

**None.** The gateway already accepts any WebSocket client. The only addition
is the optional `ide_context` field in chat messages, which the gateway passes
through as-is. Command responses (conversations, chat_history) are returned as
JSON strings inside the `content` field of response messages — the extension
parses these to detect command results vs regular text responses.

### Key design decisions

- **No auto-launch** — The vault password requires manual terminal input on
  first start, making auto-launch from the extension impossible.
- **No clear/wipe button** — The gateway's `clear` command is destructive
  (wipes ALL agent memories). This is never exposed as a UI button.
- **New Chat = UI-only** — The "New Chat" button clears the chat panel without
  sending any command to the gateway. The agent's memory is untouched.
- **Tool steps are transient** — Removed from the chat when the agent's
  response arrives, keeping the UI clean.

## Comparison with Claude Code Extension

| | EloPhanto Extension | Claude Code Extension |
|---|---|---|
| **Architecture** | WebSocket client → shared gateway | Embedded CLI subprocess |
| **Cross-channel** | Same conversation from VS Code, Telegram, CLI, web | VS Code only |
| **Background work** | Autonomous mind runs even when VS Code is closed | Stops when VS Code closes |
| **Capabilities** | Full agent (browser, email, payments, org, swarm) | Coding assistant |
| **State** | Persistent across sessions and channels | Per-session |
| **Multi-model** | Routes to different models per task type | Single model |

## Files

- **Extension:** `vscode-extension/`
- **Gateway protocol:** `core/protocol.py`
- **Channel adapter base:** `channels/base.py`
- **Web dashboard client (reference):** `web/src/lib/gateway.ts`
- **Web dashboard protocol (reference):** `web/src/lib/protocol.ts`
