# Browser Automation (Node.js Bridge)

## Overview

EloPhanto controls real Chrome browsers via a Node.js bridge built on [FellouAI/eko](https://github.com/FellouAI/eko).
Python communicates with a Node.js subprocess over JSON-RPC (stdin/stdout), delegating all browser
operations to a TypeScript browser engine that follows EKO's proven patterns for input handling,
click simulation, scrolling, and anti-detection.

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
- **`core/browser_manager.py`** — Bridge client (~800 lines) with profile management, Chrome detection, and cookie handling
- **`bridge/browser/src/server.ts`** — JSON-RPC server wrapping `AwareBrowserAgent`
- **`bridge/browser/src/browser-agent.ts`** — Full browser automation engine (Playwright, stealth plugin, element stamping, event dispatch)

**Protocol:**
```
Initialize: {"id": 1, "method": "initialize", "params": {"mode": "profile", ...}}
Set task:   {"id": 2, "method": "set_task_context", "params": {"task": "Publish article on Substack"}}
Tool call:  {"id": 3, "method": "call_tool", "params": {"name": "browser_navigate", "args": {"url": "https://..."}}}
Response:   {"id": 3, "result": {"success": true, "url": "...", "title": "...", "elements": [...]}}
Error:      {"id": 3, "error": {"message": "...", "code": -1}}
```

The `set_task_context` method forwards the user's current goal to the browser bridge.
The vision model includes this task in its analysis prompt, preventing goal drift
(e.g., creating a Note when asked to publish an Article).

## Connection Modes

| Mode | Config `mode` | Use Case |
|------|--------------|----------|
| **Fresh** | `fresh` | Launch a clean Chrome instance (default) |
| **CDP Port** | `cdp_port` | Connect to a running Chrome with `--remote-debugging-port` |
| **CDP WebSocket** | `cdp_ws` | Connect via a specific WebSocket endpoint (e.g. from a remote browser) |
| **Profile** | `profile` | Use your Chrome profile — direct access when Chrome is closed, safe copy when Chrome is running |

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

Uses your real Chrome profile with all cookies and sessions preserved.
Automatically adapts depending on whether Chrome is already running.

```yaml
browser:
  enabled: true
  mode: profile
  user_data_dir: ""  # Empty = auto-detect default Chrome profile
  profile_directory: Profile 1  # Or "Default", "Profile 2", etc.
```

**How it works — two paths depending on Chrome state:**

**Chrome is NOT running** (optimal path):
1. Uses the original Chrome profile directory directly — no copy needed
2. Backs up Preferences so the user's Chrome opens normally afterward
3. Cleans stale lock files, crash state, and session restore files
4. Launches via Playwright's `launchPersistentContext` with the real profile
5. On close, restores the original Preferences file

**Chrome IS running** (safe copy path):
1. Detects Chrome is running via `pgrep` (macOS/Linux) or `tasklist` (Windows)
2. Copies the selected profile to `/tmp/elophanto-chrome-profile`, skipping cache directories (Service Worker, Cache, Code Cache, GPUCache, etc.) to reduce copy time
3. Files locked by Chrome are skipped gracefully — the rest of the profile copies fine
4. Lock files are removed, crash state is cleaned, session restore files deleted
5. Launches a **separate** Chrome instance with the copy — your existing Chrome stays open and untouched
6. On macOS, removes Playwright's default `--use-mock-keychain` flag so Chrome can access the real macOS Keychain and decrypt cookies from the copied profile

The copy is reused on subsequent runs for fast startup. If the profile source or directory changes, a fresh copy is made automatically.
The first copy may take 10-30 seconds for large profiles. Subsequent launches reuse the copy and start in under a second.

When `user_data_dir` is empty, the default Chrome path is auto-detected:
- macOS: `~/Library/Application Support/Google/Chrome`
- Linux: `~/.config/google-chrome`
- Windows: `%LOCALAPPDATA%\Google\Chrome\User Data`

## Tools (48)

The bridge exposes 48 browser tools from `AwareBrowserAgent`. Key categories:

### Navigation & Reading

| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to URL, returns elements with indices |
| `browser_extract` | Full page text/HTML extraction |
| `browser_read_semantic` | Compressed screen-reader-style view (headings, landmarks, forms) |
| `browser_screenshot` | Labeled screenshot with colored element overlays + pseudo-HTML |
| `browser_get_elements` | Interactive elements as pseudo-HTML via DOM tree traversal |
| `browser_get_html` | Full HTML source |
| `browser_list_tabs` | List open tabs |

### Interaction

| Tool | Description |
|------|-------------|
| `browser_click` | Click by element index |
| `browser_click_text` | Click by visible text match |
| `browser_click_batch` | Multiple clicks in one call |
| `browser_type` | Type into element by index |
| `browser_press_key` | Press keyboard key (Enter, Escape, Tab, arrow keys, shortcuts) |
| `browser_type_text` | Type text without targeting a specific element |
| `browser_scroll` | Scroll page or container |
| `browser_select_option` | Select/deselect form controls |
| `browser_drag_drop` | Drag-and-drop by index or coordinates |
| `browser_hover_element` | Hover by index |
| `browser_paste_html` | Paste HTML as rich text into focused element (ClipboardEvent with text/html DataTransfer) |
| `browser_upload_file` | Upload file(s) to `<input type="file">` by element index |
| `browser_file_chooser` | Upload file(s) via native file dialog triggered by clicking a button |

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

### EKO DOM Tree System

The bridge uses EKO's DOM tree traversal for element identification (ported from
[FellouAI/eko](https://github.com/FellouAI/eko)'s `build-dom-tree.ts`). When
`browser_screenshot` or `browser_get_elements` is called, a JavaScript module is
injected into the page that:

1. **Recursively traverses** the entire DOM including iframes and shadow DOM
2. **Identifies interactive elements** via comprehensive checks:
   - HTML tags (`a`, `button`, `input`, `select`, `textarea`, etc.)
   - ARIA roles (`button`, `link`, `checkbox`, `combobox`, `tab`, `menuitem`, etc.)
   - Event listeners (`onclick`, `onmousedown`, `ontouchstart`, framework bindings like `@click`, `ng-click`, `v-on:click`)
   - Styling (`cursor: pointer` with parent deduplication)
   - Attributes (`contenteditable`, `tabindex`, `draggable`, `aria-expanded/pressed/selected`)
3. **Checks visibility** — `offsetWidth/Height`, `display`, `visibility`
4. **Checks top-element status** — uses `document.elementFromPoint()` to verify the element isn't behind a modal or overlay
5. **Draws colored overlays** — 12 cycling colors, bounding boxes with index labels at z-index max
6. **Returns pseudo-HTML** — e.g., `[15]:<button class="primary" aria-label="Publish">Publish Article</button>`
7. **Stores element references** — `window.get_highlight_element(index)` retrieves the exact element for clicking

The combined `takeScreenshotWithElements()` method ensures index consistency:
screenshot labels and pseudo-HTML indices always match because they're generated
in the same call. Falls back to the legacy CSS selector approach if injection fails.

### Element Resolution

When clicking/typing by index, the bridge resolves elements via:
1. `window.get_highlight_element(idx)` — stored reference from DOM tree traversal
2. `document.querySelector('[data-aware-idx="idx"]')` — legacy stamped attribute
3. Positional fallback via `querySelectorAll(selectors)[idx]`

### Input Handling (EKO-style fallback chain)

`browser_type` follows EKO's two-tier approach:

1. **Playwright `fill()`** — tried first as the fast path. Works for standard HTML inputs and textareas.
2. **DOM-level fallback** — if `fill()` fails (React controlled inputs, contenteditable editors, iframes), falls back to direct DOM manipulation:
   - **React inputs**: Uses the prototype value setter hack (`Object.getOwnPropertyDescriptor(el.__proto__, 'value').set.call(el, text)`) + dispatches `input` and `change` events so React's state updates
   - **Contenteditable**: Sets `textContent` directly for rich text editors (Slate.js, Draft.js, ProseMirror)
   - **Iframes**: Traverses into iframes to find the actual input element
   - **Wrapper elements**: Drills through `<div>` wrappers to find the inner `<input>` or `<textarea>`

### Click Simulation (human-like)

`browser_click` uses EKO's mouse movement pattern:

1. Gets the element's bounding box
2. Moves the cursor to the element center with ±5px random jitter and 3-7 motion steps
3. Clicks with a random delay (20-70ms) to simulate human timing
4. If Playwright click fails, falls back to the full DOM event dispatch chain (pointerdown → mousedown → pointerup → mouseup → click)

### Smart Scrolling

`browser_scroll` uses EKO's dual-container strategy with direct pixel amounts (default 300px):

1. Checks if the page itself is scrollable first
2. Finds all scrollable containers (overflow-y: auto/scroll with overflowing content)
3. Traverses into iframes to find scrollable elements
4. Ranks containers by z-index (highest first), then by visible area
5. Scrolls both the primary container (highest z-index — typically modals/overlays) and the secondary container (tallest — typically the main content)

The `amount` parameter is in pixels (default: 300). `browser_scroll_container` also accepts pixels (default: 300) and auto-detects modals/dialogs.

### Rich Text Paste

`browser_paste_html` enables pasting formatted content into rich text editors that don't render markdown (Medium, Substack, WordPress visual editor, Google Docs, etc.):

1. Takes `html` content and optional `text` plain-text fallback
2. Creates a `DataTransfer` with both `text/html` and `text/plain` MIME types
3. Dispatches a synthetic `ClipboardEvent('paste')` on the focused element
4. The editor receives formatted rich text as if the user pasted from clipboard

This bypasses the system clipboard entirely — no permissions needed, works reliably across platforms. The agent should convert markdown to HTML before calling this tool.

### File Upload

Two tools handle file uploads depending on the page's implementation:

**`browser_upload_file`** — for visible `<input type="file">` elements:
1. Resolves the element by index (same chain as click: `get_highlight_element` → `data-aware-idx` → positional)
2. If the element is a wrapper (e.g., `<div>`), drills into it to find a nested `<input type="file">`
3. Sets file(s) via Playwright's `setInputFiles()` — no native dialog opened
4. Supports multiple files if the input has the `multiple` attribute

**`browser_file_chooser`** — for buttons/areas that trigger a native file picker:
1. Registers a `page.waitForEvent('filechooser')` listener (10s timeout)
2. Clicks the trigger element (human-like with jitter, DOM fallback)
3. Intercepts the native file dialog and sets files via `fileChooser.setFiles()`
4. Use this when there is no visible `<input type="file">` in the element list — just an "Upload" button or drop zone

Both tools accept absolute file paths and verify file existence before attempting upload.

## Anti-Detection

The bridge uses `playwright-extra` with the stealth plugin, which patches common
automation fingerprints. Additionally:
- System Chrome is used by default (`use_system_chrome: true`)
- Anti-detection Chromium flags: `--disable-blink-features=AutomationControlled`, `--disable-features=IsolateOrigins,site-per-process,ChromeWhatsNewUI`
- Profile stability flags: `--disable-sync`, `--disable-background-networking`, `--disable-component-update`, `--noerrdialogs`, `--disable-session-crashed-bubble`, `--hide-crash-restore-bubble`
- Human-like mouse movement before clicks: cursor moves to element with random ±5px jitter and 3-7 motion steps, click delay randomized between 20-70ms
- Full DOM event dispatch chain as fallback (pointerdown → mousedown → pointerup → mouseup → click)

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
  viewport_width: 1536        # Browser viewport width
  viewport_height: 864        # Browser viewport height
  vision_model: google/gemini-2.0-flash-001  # OpenRouter model for screenshot analysis
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
