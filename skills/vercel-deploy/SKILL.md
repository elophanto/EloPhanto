# Deploy to Vercel

## Description
Deploy applications and websites to Vercel. Handles project linking, environment
variables, preview vs production deploys, and framework auto-detection.

## Triggers
- vercel
- deploy to vercel
- deploy frontend
- deploy static site
- deploy next.js
- preview deployment
- vercel deploy

## Instructions

### When to Use Vercel

Vercel is the right choice for:
- Static sites and marketing pages
- Next.js frontends with simple APIs (response time < 10s)
- JAMstack sites, React SPAs, Vite apps

**Do NOT use Vercel** if any API route calls an LLM, does heavy processing,
streams data, or uses WebSockets — these will hit the **10-second serverless
function timeout** on free tier (60s on Pro). Use Railway instead.

### Deploy Workflow

1. **Build locally first** — always run `npm run build` before deploying.
   Fix all build errors locally. Deploying broken code wastes time.

2. **Create database if needed** — if the project needs persistence, call
   `create_database` with a project name. It returns `url`, `anon_key`,
   `service_role_key`, and `db_url` automatically. **Never ask the user for
   Supabase keys** — they are auto-generated.

3. **Deploy** using the `deploy_website` tool:
   ```
   deploy_website(
     project_path="/path/to/project",
     provider="vercel",
     name="my-project",         # optional
     env_vars={                  # from create_database result
       "NEXT_PUBLIC_SUPABASE_URL": url,
       "NEXT_PUBLIC_SUPABASE_ANON_KEY": anon_key,
       "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
       "DATABASE_URL": db_url
     },
     production=true             # false for preview deploy
   )
   ```

4. **Verify** — check the returned URL in the browser.

### Token Setup

The `deploy_website` tool reads the Vercel token from the vault automatically.
If not set, it will tell the user what to do:
```
vault_set key=vercel_token value=YOUR_TOKEN
```

Get the token at: vercel.com → Settings → Tokens → Create Token (scope: full account).

The Vercel CLI must be installed: `npm install -g vercel`

### How It Works Under the Hood

The `deploy_website` tool runs:
```bash
# Set each env var
printf "%s" "$VALUE" | vercel env add KEY production --token $TOKEN --yes

# Deploy
vercel --yes --token $TOKEN --prod [--name project-name]
```

It returns the deployment URL from the CLI output.

### Preview vs Production

- **Default is production** (`production=true`).
- For preview deploys, set `production=false`.
- Preview URLs look like: `https://my-app-abc123.vercel.app`
- Production URLs use the project's domain or: `https://my-app.vercel.app`

### Framework Auto-Detection

Vercel auto-detects 40+ frameworks from `package.json`:
- Next.js, Nuxt, Remix, SvelteKit, Astro, Vite, Create React App, Gatsby,
  Angular, Vue CLI, Eleventy, Hugo, Jekyll, and more.

No framework configuration needed — just deploy.

### Vercel Free Tier Limits

- Unlimited static sites and deployments
- 10-second serverless function timeout (60s on Pro)
- 100GB bandwidth/month
- 1 team member

### Anti-Patterns

- **Don't deploy without building locally** — `npm run build` catches errors
  before burning deploy minutes.
- **Don't hardcode API keys in source** — use `env_vars` parameter to inject
  them into Vercel's environment.
- **Don't use Vercel for LLM-calling APIs** — they will timeout. Use Railway.
- **Don't ask the user for Supabase anon/service keys** — `create_database`
  returns them automatically.

## Verify

- The deploy command was actually run and the build/log output (or deploy URL) is captured
- The deployed URL was opened and returned a 2xx; key routes were sampled, not just the index
- Environment variables required by the app are present in the target environment; missing-var failures were ruled out
- A rollback plan (previous deployment ID, git SHA, or one-line revert command) is documented before promoting to production
- Health/observability check (logs, error tracker, status page) was inspected post-deploy; baseline error rate is recorded
- DNS / domain / SSL configuration was confirmed, not assumed to carry over from previous deploys
