# 31 — Web Deployment

Deploy websites to the internet and create databases from conversation. The agent scaffolds a project, builds it, provisions infrastructure, and returns a live URL — all from a single prompt like "Build me a SaaS dashboard and put it live."

## Architecture

Three hosting providers, each for a different workload:

| Provider | Use Case | Limits |
|----------|----------|--------|
| **Vercel** | Static sites, Next.js frontends, simple/fast APIs (< 10s) | Free: unlimited static, 10s function timeout (60s Pro) |
| **Railway** | Long-running APIs (LLM calls, streaming), WebSockets, cron, backends | Free: $5/mo credit, no timeout limits |
| **Supabase** | Database, auth, storage, realtime — always, regardless of host | Free: 2 projects, 500MB DB, 1GB storage |

### Provider Decision Framework

| Project Type | Provider | Reason |
|---|---|---|
| Static site / marketing page | Vercel | Free, fast CDN |
| Next.js with simple APIs (< 10s) | Vercel + Supabase | Native Next.js support |
| App with LLM API calls | **Railway** + Supabase | Vercel times out at 10s |
| App with streaming / WebSockets | **Railway** + Supabase | No timeout limits |
| App with cron jobs / queues | **Railway** + Supabase | Persistent processes |
| Pure API backend (no frontend) | **Railway** + Supabase | Server process |
| When in doubt | **Railway** | No timeout limits |

**Critical**: Vercel has a **10-second serverless function timeout** on the free tier (60s on Pro). Any API route that calls OpenAI/Anthropic, does heavy processing, or streams data **will fail** on Vercel. Always use Railway for those projects.

## Tools

### `deploy_website`

Deploy a web project to Vercel or Railway.

**Permission**: DESTRUCTIVE

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_path` | string | yes | — | Path to the project directory |
| `provider` | string | no | `"auto"` | `"auto"`, `"vercel"`, or `"railway"` |
| `name` | string | no | — | Project name on the platform |
| `env_vars` | object | no | — | Environment variables to set on the platform |
| `production` | boolean | no | `true` | Deploy to production |

**Auto-detection** (when `provider="auto"`):

The tool scans the project to detect long-running patterns:

1. **API route scanning** — checks `src/app/api/`, `app/api/`, `pages/api/`, `src/pages/api/` for `.ts` and `.js` files containing:
   - `openai`, `anthropic` (LLM SDK imports)
   - `ReadableStream` (streaming responses)
   - `WebSocket`, `socket.io` (real-time connections)
   - `setTimeout` (long-running timers)

2. **Dependency scanning** — checks `package.json` for:
   - `ws`, `socket.io` (WebSocket libraries)
   - `bullmq`, `pg-boss` (job queue libraries)

3. **Procfile detection** — if `Procfile` exists, the project likely runs a custom server.

Any match routes to Railway. No matches defaults to Vercel.

**Vercel deploy flow**:
```bash
# Set env vars (each key separately)
printf "%s" "$VALUE" | vercel env add KEY production --token $TOKEN --yes

# Deploy
vercel --yes --token $TOKEN --prod [--name project-name]
```

**Railway deploy flow**:
```bash
# Set env vars
RAILWAY_TOKEN=$TOKEN railway variables set KEY1=VAL1 KEY2=VAL2

# Deploy
RAILWAY_TOKEN=$TOKEN railway up --detach
```

**Returns**:
```json
{
  "status": "deployed",
  "provider": "vercel",
  "url": "https://my-app-abc123.vercel.app",
  "output_tail": "..."
}
```

### `create_database`

Create a Supabase project with PostgreSQL database, auth, storage, and realtime.

**Permission**: DESTRUCTIVE

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | yes | — | Project name (e.g. `"my-saas-app"`) |
| `region` | string | no | `"us-east-1"` | Supabase region |
| `sql` | string | no | — | Initial SQL to run (CREATE TABLE, etc.) |

**Flow**:

1. Resolve `supabase_access_token` from vault
2. Get organization ID (from config or auto-detect via list orgs API)
3. Generate secure database password (`secrets.token_urlsafe(24)`)
4. Create project via `POST https://api.supabase.com/v1/projects`
5. Poll every 5s until status is `ACTIVE_HEALTHY` (timeout: 120s)
6. Retrieve API keys (anon + service_role) via `/projects/{ref}/api-keys`
7. If `sql` provided, execute via `POST /projects/{ref}/sql`

**Returns**:
```json
{
  "status": "created",
  "project_id": "abc123",
  "url": "https://abc123.supabase.co",
  "anon_key": "eyJ...",
  "service_role_key": "eyJ...",
  "db_url": "postgresql://postgres.abc123:PASS@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
  "db_pass": "...",
  "region": "us-east-1",
  "sql_result": "SQL executed successfully."
}
```

### `deployment_status`

Check the deployment status of a project.

**Permission**: SAFE

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_path` | string | yes | — | Path to the project directory |
| `provider` | string | no | `"auto"` | `"auto"`, `"vercel"`, or `"railway"` |

**Auto-detection**: reads `.vercel/project.json` (Vercel) or `railway.json`/`railway.toml` (Railway) from the project directory.

**Returns** (Vercel):
```json
{
  "provider": "vercel",
  "project_id": "prj_abc123",
  "recent_deployments": "..."
}
```

**Returns** (Railway):
```json
{
  "provider": "railway",
  "status_output": "...",
  "url": "https://my-app.up.railway.app"
}
```

## Configuration

```yaml
deployment:
  enabled: false                              # Enable deployment tools
  default_provider: auto                      # auto | vercel | railway
  vercel_token_ref: "vercel_token"            # Vault key for Vercel token
  railway_token_ref: "railway_token"          # Vault key for Railway token
  supabase_token_ref: "supabase_access_token" # Vault key for Supabase token
  supabase_org_id: ""                         # Optional: explicit org ID
```

**`DeploymentConfig`** dataclass in `core/config.py`.

### Token Setup

Store tokens in the vault before using deployment tools:

```
vault_set key=vercel_token value=YOUR_VERCEL_TOKEN
vault_set key=railway_token value=YOUR_RAILWAY_TOKEN
vault_set key=supabase_access_token value=YOUR_SUPABASE_ACCESS_TOKEN
```

**Where to get tokens**:

- **Vercel**: [vercel.com/account/tokens](https://vercel.com/account/tokens) → Create Token (scope: full account)
- **Railway**: [railway.com/account/tokens](https://railway.com/account/tokens) → Create Token
- **Supabase**: [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens) → Generate New Token

### Supabase Token Clarification

Supabase has two layers of authentication — don't confuse them:

| Token | What It Is | Who Uses It | Where to Get It |
|-------|-----------|-------------|-----------------|
| **Access Token** | Personal account token for the **Management API** | The `create_database` tool — to create projects, list orgs, fetch API keys | Dashboard → Account → Access Tokens |
| **`anon` key** | Per-project JWT with low privileges (respects RLS) | Your deployed app's client-side code | Auto-retrieved by `create_database` after project creation |
| **`service_role` key** | Per-project JWT with full access (bypasses RLS) | Your deployed app's server-side code | Auto-retrieved by `create_database` after project creation |

**You only store the Access Token in the vault.** The per-project keys (`anon`, `service_role`, `DATABASE_URL`) are automatically fetched when a project is created and returned in the tool result. Pass them as `env_vars` to `deploy_website`.

The optional `supabase_org_id` in config specifies which organization to create projects under. If left empty, the tool auto-detects your first organization via the Management API.

### CLI Prerequisites

The Vercel and Railway tools shell out to their respective CLIs:

```bash
npm install -g vercel        # Vercel CLI
npm install -g @railway/cli  # Railway CLI
```

Supabase uses the Management API directly (no CLI needed).

## Deployment Workflow

The recommended workflow for deploying a project:

1. **Scaffold** the project locally (Next.js, Vite, etc.)
2. **Create database** with `create_database` if the project needs persistence
3. **Wire env vars** — pass Supabase credentials to `deploy_website`:
   - `NEXT_PUBLIC_SUPABASE_URL` — project URL
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` — anon key (safe for client)
   - `SUPABASE_SERVICE_ROLE_KEY` — service role key (server-side only)
   - `DATABASE_URL` — direct Postgres connection string
4. **Build locally** — always run `npm run build` before deploying to catch errors
5. **Deploy** with `deploy_website`
6. **Verify** — check the returned URL

## Agent Integration

### Dependency Injection

Deployment tools receive their dependencies via `Agent._inject_deployment_deps()`:

```python
def _inject_deployment_deps(self) -> None:
    deploy_tools = ("deploy_website", "create_database", "deployment_status")
    for tool_name in deploy_tools:
        tool = self._registry.get(tool_name)
        if tool:
            tool._config = self._config.deployment
            if self._vault:
                tool._vault = self._vault
```

Only wired when `deployment.enabled: true` in config.

### System Prompt

When deployment is enabled, the planner injects a `<deployment>` section into the system prompt with:
- Available tools and their purposes
- Decision framework (when to use which provider)
- Deployment workflow steps

### Skill

The `web-deployment` skill (`skills/web-deployment/SKILL.md`) triggers on keywords like "deploy", "hosting", "go live", "launch", "production". It provides the agent with the full decision framework, provider-specific notes, and anti-patterns.

## Files

| File | Description |
|------|-------------|
| `tools/deployment/__init__.py` | Package init |
| `tools/deployment/deploy_tool.py` | `deploy_website` — Vercel + Railway deployment |
| `tools/deployment/database_tool.py` | `create_database` — Supabase project provisioning |
| `tools/deployment/deployment_status_tool.py` | `deployment_status` — check live deployments |
| `core/config.py` | `DeploymentConfig` dataclass + parsing |
| `core/agent.py` | `_inject_deployment_deps()` + initialization |
| `core/planner.py` | `_TOOL_DEPLOYMENT` system prompt section |
| `skills/web-deployment/SKILL.md` | Deployment skill with decision framework |

## Anti-Patterns

- **Don't deploy to Vercel if any API route calls an LLM** — it will timeout. Auto-detect catches most cases but double-check manually.
- **Don't hardcode API keys** — use `env_vars` parameter on `deploy_website` to inject them into the platform's environment.
- **Don't skip `npm run build`** — deploying broken code wastes time and deploy minutes. Build locally first, fix errors, then deploy.
- **Don't create multiple Supabase projects for the same app** — one project gives you database + auth + storage + realtime. Use tables, not projects, to separate concerns.
- **Don't forget to pass database credentials** — the most common deployment failure is the app trying to connect to Supabase without the URL/key env vars.
