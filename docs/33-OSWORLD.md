# 33 — OSWorld: Desktop GUI Agent

OSWorld is the first scalable benchmark for multimodal agents operating in real computer environments. It tests 369 desktop tasks across Ubuntu, Windows, and macOS — file management, web browsing, email, productivity apps, cross-application workflows. Humans score 72%, best AI agents only 12%.

Homepage: https://os-world.github.io
Repo: https://github.com/xlang-ai/OSWorld

## Why This Matters

EloPhanto currently operates at the API/CLI level — browser bridge, shell commands, HTTP tools. OSWorld requires **pixel-level GUI control**: reading screenshots, clicking buttons at x,y coordinates, typing into text fields, dragging, scrolling. Adding this capability means EloPhanto can operate any desktop application like a human would, not just APIs.

## Architecture

### Observe-Act Loop

```
┌─────────────────────────────────────────────────────────┐
│                    EloPhanto Agent                       │
│                                                         │
│  instruction + screenshot ──▶ LLM (vision) ──▶ action   │
│         ▲                                       │       │
│         │              loop (max N steps)        │       │
│         │                                       ▼       │
│  ┌──────┴──────────────────────────────────────────┐    │
│  │            Desktop Controller                    │    │
│  │  screenshot ◀── VM ──▶ pyautogui commands        │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

The agent operates in a loop:
1. Capture screenshot (+ optional accessibility tree)
2. Send screenshot + instruction + action history to vision LLM
3. LLM returns next action (click, type, scroll, hotkey, etc.)
4. Execute action on VM via pyautogui over HTTP
5. Wait, capture new screenshot, repeat
6. LLM emits `DONE` or `FAIL` when finished

### VM Communication

OSWorld runs a lightweight HTTP server inside the VM (port 5000) that exposes:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/screenshot` | GET | Capture screenshot as PNG bytes |
| `/accessibility` | GET | Get accessibility tree (AT) |
| `/terminal` | GET | Get terminal output |
| `/execute` | POST | Run pyautogui command on VM |
| `/run_python` | POST | Run arbitrary Python script |
| `/run_bash` | POST | Run bash script |
| `/file` | POST | Download file from VM |
| `/setup` | POST | Run setup commands |

EloPhanto talks to this HTTP server — no direct VM API needed at runtime.

### Virtualization Providers

| Provider | Use Case | Requirements |
|----------|----------|--------------|
| **VMware** | Desktop/laptop | VMware Workstation Pro (or Fusion on Mac) |
| **VirtualBox** | Desktop/laptop (free) | VirtualBox installed |
| **Docker** | Servers with KVM | Docker + KVM support |
| **AWS** | Large-scale parallel | AWS credentials + host-client setup |

## Observation Space

Four observation types, in order of information richness:

| Type | Description | Best For |
|------|-------------|----------|
| `screenshot` | Raw PNG of current screen | Vision models (GPT-4V, Claude) |
| `a11y_tree` | Accessibility tree (text-based UI structure) | Text-only models |
| `screenshot_a11y_tree` | Both combined | Best accuracy |
| `som` | Set-of-Mark — screenshot with numbered UI element overlays | Precise element targeting |

Default screen size: 1920×1080.

## Action Space

### PyAutoGUI Mode (default)

The agent outputs valid Python code using `pyautogui`. This is the most flexible action space:

```python
import pyautogui
pyautogui.click(500, 300)                    # click at coordinates
pyautogui.typewrite("hello world")           # type text
pyautogui.hotkey("ctrl", "s")                # keyboard shortcut
pyautogui.scroll(-3)                         # scroll down
pyautogui.moveTo(100, 200)                   # move cursor
pyautogui.drag(100, 0)                       # drag relative
```

### Computer-13 Mode (structured)

13 discrete action types with typed parameters:

| Action | Parameters | Description |
|--------|-----------|-------------|
| `CLICK` | x, y, button?, num_clicks? | Click at position |
| `DOUBLE_CLICK` | x, y | Double-click |
| `RIGHT_CLICK` | x, y | Right-click |
| `MOVE_TO` | x, y | Move cursor |
| `DRAG_TO` | x, y | Drag to position (left button held) |
| `MOUSE_DOWN` | button? | Press mouse button |
| `MOUSE_UP` | button? | Release mouse button |
| `SCROLL` | dx, dy | Scroll wheel |
| `TYPING` | text | Type text string |
| `PRESS` | key | Press and release key |
| `KEY_DOWN` | key | Hold key down |
| `KEY_UP` | key | Release key |
| `HOTKEY` | keys[] | Key combination |
| `WAIT` | — | Wait for next action |
| `DONE` | — | Task complete |
| `FAIL` | — | Task cannot be completed |

## What EloPhanto Needs

### 1. Desktop Controller (`core/desktop_controller.py`)

Wraps OSWorld's VM HTTP API:

```python
class DesktopController:
    """Communicates with a VM's HTTP server for screenshots and actions."""

    def __init__(self, vm_ip: str, server_port: int = 5000):
        self.base_url = f"http://{vm_ip}:{server_port}"

    async def screenshot(self) -> bytes:
        """GET /screenshot → PNG bytes."""

    async def accessibility_tree(self) -> str:
        """GET /accessibility → AT text."""

    async def execute_pyautogui(self, command: str) -> dict:
        """POST /execute — run pyautogui code on VM."""

    async def run_python(self, script: str) -> dict:
        """POST /run_python — run arbitrary Python."""

    async def run_bash(self, script: str, timeout: int = 30) -> dict:
        """POST /run_bash — run shell command."""

    async def get_file(self, path: str) -> bytes:
        """POST /file — download file from VM."""
```

### 2. Desktop Tools (`tools/desktop/`)

| Tool | Permission | Description |
|------|-----------|-------------|
| `desktop_connect` | MODERATE | Connect to a VM by IP (or start one via provider) |
| `desktop_screenshot` | SAFE | Capture and return screenshot for vision analysis |
| `desktop_click` | MODERATE | Click/double-click/right-click at x,y |
| `desktop_type` | MODERATE | Type text or press key/hotkey |
| `desktop_scroll` | SAFE | Scroll at current position |
| `desktop_drag` | MODERATE | Drag from current position to x,y |
| `desktop_cursor` | SAFE | Move cursor without clicking |
| `desktop_shell` | MODERATE | Run shell command inside the VM |
| `desktop_file` | SAFE | Download file from VM for inspection |

### 3. Vision Loop Integration

The observe-act loop should integrate with the existing agent architecture:

- **Planner prompt section** (`_TOOL_DESKTOP`): teaches the LLM how to interpret screenshots and choose actions
- **Screenshot injection**: screenshots sent as base64 images in the LLM conversation (Claude and GPT-4V both support image inputs)
- **Action history**: last N actions + their screenshots kept in context for trajectory awareness
- **Termination**: LLM outputs a `DONE` or `FAIL` signal to exit the loop

### 4. OSWorld Benchmark Runner

Optional but valuable — a runner that:
1. Loads task configs from `evaluation_examples/`
2. Sets up VM via provider (snapshot revert)
3. Runs the observe-act loop with EloPhanto as the agent
4. Evaluates results using OSWorld's built-in evaluation functions
5. Logs trajectories (screenshots + actions per step) for analysis

## Config

```yaml
desktop:
  enabled: false
  provider: vmware          # vmware | virtualbox | docker | aws
  vm_ip: "192.168.1.100"    # VM IP (or auto-detect)
  server_port: 5000          # VM HTTP server port
  screen_width: 1920
  screen_height: 1080
  observation_type: screenshot_a11y_tree   # screenshot | a11y_tree | screenshot_a11y_tree | som
  action_space: pyautogui                  # pyautogui | computer_13
  max_steps: 15              # max actions per task
  sleep_after_action: 1.0    # seconds to wait after each action
```

## Prerequisites

To run OSWorld tasks:

1. **VM image** — download Ubuntu/Windows/macOS VM from OSWorld releases
2. **Virtualization** — one of: VMware, VirtualBox, Docker+KVM, or AWS
3. **VM HTTP server** — runs inside the VM automatically (port 5000)
4. **Vision-capable LLM** — Claude (sonnet/opus with vision), GPT-4V, or Gemini Pro Vision
5. **Python deps** — `gymnasium`, `requests` (already likely available), `Pillow` for image processing

## Scope vs Browser Bridge

| Capability | Browser Bridge | Desktop Controller |
|-----------|---------------|-------------------|
| Target | Web pages in Chrome | Entire desktop (any app) |
| Input | DOM elements, CSS selectors | x,y pixel coordinates |
| Actions | Click element, fill form, navigate | Click, type, scroll, drag anywhere |
| Observation | DOM tree, element stamps | Screenshots, accessibility tree |
| Use case | Web automation, scraping | OS tasks, native apps, cross-app workflows |
| Protocol | JSON-RPC over stdin/stdout | HTTP to VM server |

They are complementary: browser bridge for precise web automation, desktop controller for everything else.

## Rate of Progress

OSWorld leaderboard (as of early 2026):

- Humans: **72.36%**
- Best agent: **~22%** (UI-TARS, Claude Computer Use, etc.)
- Most agents: 5–15%

The gap shows this is an unsolved frontier — meaningful improvements here would be significant.
