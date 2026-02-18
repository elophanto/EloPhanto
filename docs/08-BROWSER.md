# Browser Automation (Node.js Bridge)

## Overview

EloPhanto controls real Chrome browsers via a Node.js bridge to the `AwareBrowserAgent` engine.
Python communicates with a Node.js subprocess over JSON-RPC (stdin/stdout), delegating all browser
operations to the battle-tested TypeScript browser engine copied from the `aware-agent` project.

## Architecture

```
Python (EloPhanto)                        Node.js (bridge/browser/)
┌───────────────────────┐    stdin       ┌─────────────────────────────────┐
│ BrowserManager        │───JSON-RPC────▶│ bridge/browser/src/server.ts    │
│ (core/browser_manager)│◀──JSON-RPC────│   └─ browser-agent.ts           │
└───────────────────────┘    stdout      └─────────────────────────────────┘
         │                                         │
   Same public API                         AwareBrowserAgent
   as before (tools                        (Playwright + stealth,
    layer unchanged)                        anti-detection, CDP)
```

**Key components:**

- **`core/node_bridge.py`** — Generic async JSON-RPC client that spawns and communicates with a Node.js subprocess
- **`core/browser_manager.py`** — Thin bridge client (~450 lines) that maps Python method calls to JSON-RPC
- **`bridge/browser/src/server.ts`** — JSON-RPC server wrapping `AwareBrowserAgent`
- **`bridge/browser/src/browser-agent.ts`** — Full browser automation engine (Playwright, stealth plugin, element stamping, event dispatch)

**Protocol:**
```
Request:  {"id": 1, "method": "call_tool", "params": {"name": "browser_navigate", "args": {"url": "https://..."}}}
Response: {"id": 1, "result": {"success": true, "url": "...", "title": "...", "elements": [...]}}
Error:    {"id": 1, "error": {"message": "...", "code": -1}}
```

## Connection Modes

| Mode | Config `mode` | Use Case |
|------|--------------|----------|
| **Fresh** | `fresh` | Launch a clean Chrome instance (default) |
| **CDP Port** | `cdp_port` | Connect to a running Chrome with `--remote-debugging-port` |
| **CDP WebSocket** | `cdp_ws` | Connect via a specific WebSocket endpoint |
| **Profile** | `profile` | Launch Chrome with your user data directory (preserves cookies, sessions, extensions) |

### Fresh Mode (default)

Launches a new Chrome instance. No existing sessions or cookies.

```yaml
browser:
  enabled: true
  mode: fresh
  headless: false
```

### CDP Port Mode

Connects to an already-running Chrome instance. Preserves all logged-in sessions.

1. Start Chrome with debugging enabled:
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222

# Windows
chrome.exe --remote-debugging-port=9222
```

2. Configure:
```yaml
browser:
  enabled: true
  mode: cdp_port
  cdp_port: 9222
```

### Profile Mode

Launches a **second** Chrome instance using a copy of your Chrome profile.
Your existing Chrome stays open and untouched.

```yaml
browser:
  enabled: true
  mode: profile
  user_data_dir: ""  # Empty = auto-detect default Chrome profile
  profile_directory: Default  # Or "Profile 1", "Profile 2", etc.
```

**How it works:**
1. Python copies the selected Chrome profile to a temp directory (`/tmp/elophanto-chrome-profile`), skipping cache directories to reduce copy time
2. Lock files are removed, crash state is cleaned, and session restore files are deleted so Chrome starts cleanly
3. The copy is reused on subsequent runs for fast startup — if the copy's cookies become stale (e.g. Chrome re-encrypted them), a fresh copy is made automatically
4. Chrome is launched via Playwright's `launchPersistentContext` with system Chrome (`channel: 'chrome'`) and anti-detection flags

The first launch may take 10-20 seconds for large profiles. Subsequent launches reuse the copy and start in under a second.

When `user_data_dir` is empty, the default Chrome path is auto-detected:
- macOS: `~/Library/Application Support/Google/Chrome`
- Linux: `~/.config/google-chrome`
- Windows: `%LOCALAPPDATA%\Google\Chrome\User Data`

## Tools (46)

The bridge exposes 46 browser tools from `AwareBrowserAgent`. Key categories:

### Navigation & Reading

| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to URL, returns elements with indices |
| `browser_extract` | Full page text/HTML extraction |
| `browser_read_semantic` | Compressed screen-reader-style view (headings, landmarks, forms) |
| `browser_screenshot` | Capture viewport (optional element highlight) |
| `browser_get_elements` | List interactive elements with index numbers |
| `browser_get_html` | Full HTML source |
| `browser_list_tabs` | List open tabs |

### Interaction

| Tool | Description |
|------|-------------|
| `browser_click` | Click by element index |
| `browser_click_text` | Click by visible text match |
| `browser_click_batch` | Multiple clicks in one call |
| `browser_type` | Type into element by index |
| `browser_scroll` | Scroll page or container |
| `browser_select_option` | Select/deselect form controls |
| `browser_drag_drop` | Drag-and-drop by index or coordinates |
| `browser_hover_element` | Hover by index |

### Data & Debugging

| Tool | Description |
|------|-------------|
| `browser_get_cookies` | Read cookies for current domain |
| `browser_get_storage` | localStorage and sessionStorage |
| `browser_get_console` | Captured console logs |
| `browser_get_network` | Network request/response log |
| `browser_eval` | Execute JavaScript in page context |
| `browser_full_audit` | Deep inspect + scripts + storage + meta in one call |

## Element Interaction

The bridge uses `AwareBrowserAgent`'s element stamping system. When `browser_navigate`
or `browser_get_elements` is called, each interactive element is stamped with a
`data-aware-idx` attribute. Subsequent `browser_click`, `browser_type`, and similar
calls use this index for reliable targeting.

The element stamping covers: links, buttons, inputs, selects, textareas, ARIA roles
(button, link, radio, checkbox, tab, menuitem, switch, slider, combobox, listbox),
contenteditable elements, onclick handlers, and cursor-pointer styled elements.

## Anti-Detection

The bridge uses `playwright-extra` with the stealth plugin, which patches common
automation fingerprints. Additionally:
- System Chrome is used by default (`use_system_chrome: true`)
- Anti-detection Chromium flags: `--disable-blink-features=AutomationControlled`, `--disable-features=IsolateOrigins,site-per-process,ChromeWhatsNewUI`
- Profile stability flags: `--disable-sync`, `--disable-background-networking`, `--disable-component-update`, `--noerrdialogs`, `--disable-session-crashed-bubble`, `--hide-crash-restore-bubble`
- The full event dispatch chain is used for clicks (pointerdown → mousedown → pointerup → mouseup → click)

## Content Sanitization

HTML content returned by tools like `browser_extract` and `browser_get_html` is sanitized on the Python side:
- `<script>` tags and content removed
- `<style>` tags and content removed
- `on*` event handlers stripped
- Password input values redacted to `[REDACTED]`
- Large base64 data URIs (>100KB) replaced with `[LARGE_DATA_URI]`

## Login & Credential Handling

When the agent encounters a login page:

1. **Profile sessions first** — in profile mode, the user's existing Chrome sessions are typically already active. The agent navigates to the site and checks if it's already logged in before doing anything else.
2. **Vault lookup** — if a login form is detected, the agent checks the encrypted credential vault (`vault_lookup` tool) for stored credentials.
3. **Interactive prompt** — if no stored credentials are found, the agent asks the user directly for their email/password in the conversation (works across CLI, Telegram, or any interface). It never tells the user to run CLI commands.
4. **Type credentials** — the agent types the provided credentials into the browser login form using `browser_type`.

The vault can be pre-populated:
```bash
elophanto vault init        # Initialize (sets master password)
elophanto vault set google.com  # Store credentials for a domain
```

Domain matching supports partial matches (e.g., `accounts.google.com` matches stored `google.com`).

## Configuration Reference

```yaml
browser:
  enabled: false              # Enable browser automation
  mode: fresh                 # fresh | cdp_port | cdp_ws | profile
  headless: false             # Run without visible window
  cdp_port: 9222              # CDP port (for cdp_port mode)
  cdp_ws_endpoint: ''         # WebSocket URL (for cdp_ws mode)
  user_data_dir: ''           # Chrome profile path (for profile mode); empty = auto-detect
  profile_directory: Default  # Profile subdirectory (Default, Profile 1, etc.)
  use_system_chrome: true     # Use system Chrome vs Playwright Chromium
  viewport_width: 1280        # Browser viewport width
  viewport_height: 720        # Browser viewport height
```

## Setup

```bash
# Build the Node.js bridge (required once)
cd bridge/browser && npm install && npx tsup && cd ../..

# System Chrome is used by default — no extra browser install needed
# For Playwright's bundled Chromium (optional):
npx playwright install chromium
```

## Bridge Lifecycle

1. **Spawn**: When the first browser tool is called, `BrowserManager.initialize()` starts the Node.js subprocess
2. **Ready**: The bridge sends a `{"id": null, "result": {"ready": true}}` signal when it's ready to accept commands
3. **RPC**: Each tool call maps to `call_tool` with `name` and `args` (e.g. `browser_navigate`, `browser_click_text`)
4. **Recovery**: If the bridge process crashes, it's automatically restarted on the next tool call
5. **Shutdown**: `BrowserManager.close()` sends a `close` RPC, then terminates the subprocess
