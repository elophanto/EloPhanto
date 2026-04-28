# Deploy to Railway

## Description
Deploy applications and backends to Railway. Handles long-running processes,
WebSockets, cron jobs, and LLM API calls with no timeout limits.

## Triggers
- railway
- deploy to railway
- deploy backend
- deploy api
- deploy server
- deploy websocket
- deploy streaming
- long running deploy

## Instructions

### When to Use Railway

Railway is the right choice for:
- APIs that call LLMs (OpenAI, Anthropic, etc.) — responses take > 10s
- Streaming / Server-Sent Events / WebSocket applications
- Background workers, cron jobs, job queues (BullMQ, pg-boss)
- Pure API backends (no frontend)
- Any app that needs persistent server processes
- **When in doubt** — Railway has no timeout limits

### Deploy Workflow

1. **Build locally first** — always run `npm run build` (or equivalent) before
   deploying. Fix all build errors locally.

2. **Create database if needed** — if the project needs persistence, call
   `create_database` with a project name. It returns `url`, `anon_key`,
   `service_role_key`, and `db_url` automatically. **Never ask the user for
   Supabase keys** — they are auto-generated.

3. **Deploy** using the `deploy_website` tool:
   ```
   deploy_website(
     project_path="/path/to/project",
     provider="railway",
     name="my-api",              # optional
     env_vars={                  # from create_database result + any other vars
       "DATABASE_URL": db_url,
       "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
       "OPENAI_API_KEY": "...",  # or any other env vars the app needs
     }
   )
   ```

4. **Verify** — check the returned URL or use `deployment_status` to confirm.

### Token Setup

The `deploy_website` tool reads the Railway token from the vault automatically.
If not set, it will tell the user what to do:
```
vault_set key=railway_token value=YOUR_TOKEN
```

Get the token at: railway.com → Account Settings → Tokens → Create Token.

The Railway CLI must be installed: `npm install -g @railway/cli`

### How It Works Under the Hood

The `deploy_website` tool runs:
```bash
# Set env vars
RAILWAY_TOKEN=$TOKEN railway variables set KEY1=VAL1 KEY2=VAL2

# Deploy (detached — returns immediately)
RAILWAY_TOKEN=$TOKEN railway up --detach

# Get the public URL
RAILWAY_TOKEN=$TOKEN railway domain
```

### Railway Free Tier

- $5/month credit (no credit card needed to start)
- No timeout limits on server processes
- Persistent processes (keeps running after deploy)
- Custom domains supported
- Automatic HTTPS

### Project Types That Need Railway

| Pattern in Code | Why Railway |
|----------------|-------------|
| `import openai` / `import anthropic` | LLM calls take 10-60s |
| `ReadableStream` / `EventSource` | Streaming responses |
| `WebSocket` / `socket.io` / `ws` | Persistent connections |
| `setTimeout` > 10s | Long timers |
| `bullmq` / `pg-boss` | Background job queues |
| `Procfile` exists | Custom server process |
| `cron` / scheduled tasks | Recurring jobs |

### Anti-Patterns

- **Don't hardcode API keys in source** — use `env_vars` parameter.
- **Don't deploy without building locally** — catch errors before deploying.
- **Don't ask the user for Supabase anon/service keys** — `create_database`
  returns them automatically.
- **Don't use Railway for simple static sites** — Vercel is free and faster
  for static content with global CDN.
