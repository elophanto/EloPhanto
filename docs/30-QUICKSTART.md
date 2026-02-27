# 5-Minute Quick Start

Get EloPhanto running and complete your first autonomous task in under 5 minutes.

---

## Step 1: Install (2 minutes)

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./setup.sh
```

The setup script handles everything:
- Creates Python virtual environment
- Installs dependencies via uv
- Sets up Node.js browser bridge
- Runs all tests (978+ passing)
- Launches configuration wizard

<p align="center">
  <img src="../misc/screenshots/terminal.png" alt="Terminal Output" width="600">
</p>

---

## Step 2: Configure LLM Provider (1 minute)

The wizard will prompt you to configure an LLM provider. Choose one:

### Option A: Ollama (Free, Local)
```bash
# Install Ollama first
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1
```

Select **Ollama** in the wizard, confirm `llama3.1` (or any installed model).

### Option B: Z.ai / GLM (Cheap, Cloud)
1. Go to https://z.ai/manage-apikey/apikey-list
2. Create API key
3. Paste key into wizard

Select **Z.ai** in the wizard.

### Option C: OpenRouter (Flexible, Cloud)
1. Go to https://openrouter.ai/keys
2. Create API key
3. Paste key into wizard

Select **OpenRouter** in the wizard.

---

## Step 3: First Run (30 seconds)

```bash
./start.sh
```

You'll see the welcome prompt:

```
┌────────────────────────────────────────────────────────────┐
│  Welcome to EloPhanto                                   │
│  117 tools available | Mode: ask_always                  │
└────────────────────────────────────────────────────────────┘

You: _
```

<p align="center">
  <img src="../misc/screenshots/chat.png" alt="Chat Interface" width="500">
</p>

---

## Step 4: Your First Task (1 minute)

Try this simple task to see EloPhanto in action:

```
Navigate to GitHub and tell me how many stars the elophanto/EloPhanto repo has
```

**What you'll see happening in real-time:**

```
✓ browser_navigate https://github.com/elophanto/EloPhanto
✓ browser_extract
✓ Found star count: 18 stars

The EloPhanto repository has 18 GitHub stars.
```

The agent:
1. Opened your real Chrome browser
2. Navigated to GitHub (using your existing session if logged in)
3. Extracted the star count from the page
4. Reported the answer

<p align="center">
  <img src="../misc/screenshots/dashboard.png" alt="Web Dashboard" width="600">
</p>

---

## Step 5: Try Something More Advanced

Now try a task that shows off EloPhanto's autonomy:

```
Research the latest post on Hacker News and summarize it
```

**Watch it work:**
```
✓ browser_navigate https://news.ycombinator.com
✓ browser_extract
✓ Found top post: "[Article Title]"
✓ Reading article...
✓ Summarizing...

Summary: [2-3 sentence summary of the article]
```

<p align="center">
  <img src="../misc/screenshots/tools.png" alt="Tools Browser" width="400">
  <img src="../misc/screenshots/knowledge.png" alt="Knowledge Base" width="400">
</p>

---

## What Else Can You Try?

Here are more first tasks to explore:

```
# Web automation
"Log into Twitter/X and tell me my follower count"

# File management
"List all Python files in the current directory"

# Research
"Search for 'EloPhanto AI agent' and summarize the top 3 results"

# Knowledge building
"Remember this: my favorite color is blue"
"Ask me: what's my favorite color?"

# System tasks
"Check my disk usage"
```

---

## Optional: Web Dashboard

For a visual interface with monitoring and multi-channel support:

```bash
./start.sh --web
```

Open http://localhost:3000 in your browser.

Features:
- Real-time chat with conversation history
- Tools & skills browser
- Knowledge base viewer
- Autonomous mind monitor
- Schedule manager
- Channels status (Telegram, Discord, Slack)

---

## Troubleshooting

### "Python 3.12+ required"
```bash
# Check your Python version
python --version

# On macOS with Homebrew
brew install python@3.12

# On Ubuntu/Debian
sudo apt update && sudo apt install python3.12
```

### "uv not found"
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### "Node.js 24+ LTS required"
```bash
# On macOS with Homebrew
brew install node@24

# On Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt install -y nodejs
```

### Browser won't open
- Make sure Chrome is installed
- Close all Chrome windows before starting EloPhanto (or use `mode: headless` in config.yaml)
- Check that port 3000 isn't already in use

### "No LLM provider configured"
```bash
./start.sh init
# Follow the prompts to set up a provider
```

---

## Next Steps

- **Read [01-PROJECT-OVERVIEW.md](01-PROJECT-OVERVIEW.md)** — Understand the architecture
- **Explore tools** — Run `./start.sh` and type "list tools"
- **Try skills** — Run `./start.sh skills list` to see 60+ bundled skills
- **Join the community** — Star the repo on GitHub, report issues, contribute

---

**You're ready!** Give EloPhanto a task and watch it work.
