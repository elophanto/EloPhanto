# Web Deployment

## Description
Deploy websites to the internet and create databases. Supports Vercel
(static/fast APIs), Railway (long-running operations), and Supabase (database).

## Triggers
- deploy
- website
- hosting
- vercel
- railway
- supabase
- go live
- put online
- launch
- production
- make it live

## Instructions

### Provider Decision Framework

Pick the right hosting provider based on what the project does:

| Project Type | Provider | Why |
|---|---|---|
| Static site / marketing page | Vercel | Free, fast CDN |
| Next.js with simple APIs (< 10s) | Vercel + Supabase | Native Next.js support |
| App with LLM API calls | **Railway** + Supabase | Vercel times out at 10s |
| App with streaming / WebSockets | **Railway** + Supabase | No timeout limits |
| App with cron jobs / queues | **Railway** + Supabase | Persistent processes |
| Pure API backend (no frontend) | **Railway** + Supabase | Server process |
| When in doubt | **Railway** | No timeout limits |

**Critical**: Vercel has a **10-second serverless function timeout** on free tier
(60s on Pro). Any API route that calls OpenAI/Anthropic, does heavy processing,
or streams data **will fail** on Vercel. Always use Railway for those projects.

The `deploy_website` tool with `provider: "auto"` detects this automatically by
scanning API routes and package.json dependencies.

### Deployment Workflow

1. **Scaffold** the project (Next.js, etc.) and get it building locally
2. **Create database** with `create_database` if the project needs persistence
3. **Wire env vars** — pass Supabase credentials to `deploy_website`:
   - `NEXT_PUBLIC_SUPABASE_URL` — project URL
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` — anon key (safe for client)
   - `SUPABASE_SERVICE_ROLE_KEY` — service role key (server-side only)
   - `DATABASE_URL` — direct Postgres connection string
4. **Build locally** — always run `npm run build` before deploying to catch errors
5. **Deploy** with `deploy_website`
6. **Verify** — check the returned URL in the browser

### Provider-Specific Notes

**Vercel**:
- Uses `vercel --yes --token $TOKEN --prod` (non-interactive)
- Env vars set via `vercel env add`
- Token stored in vault as `vercel_token`
- Free tier: unlimited static sites, 10s function timeout

**Railway**:
- Uses `RAILWAY_TOKEN=$TOKEN railway up --detach`
- Env vars set via `railway variables set KEY=VALUE`
- Token stored in vault as `railway_token`
- Free tier: $5/month credit, no timeout limits

**Supabase**:
- Created via Management API (no CLI needed)
- Token stored in vault as `supabase_access_token`
- Free tier: 2 projects, 500MB database, 1GB file storage
- Includes Postgres, Auth, Storage, Realtime out of the box

### Anti-Patterns

- **Don't deploy to Vercel if any API route calls an LLM** — it will timeout.
  The auto-detect catches most cases but double-check manually.
- **Don't hardcode API keys** — use env_vars parameter on `deploy_website`
  to inject them into the platform's environment.
- **Don't skip `npm run build`** — deploying broken code wastes time and
  deploy minutes. Build locally first, fix errors, then deploy.
- **Don't create multiple Supabase projects for the same app** — one project
  gives you database + auth + storage + realtime. Use tables, not projects,
  to separate concerns.
- **Don't forget to pass database credentials** — the most common deployment
  failure is the app trying to connect to Supabase without the URL/key env vars.
