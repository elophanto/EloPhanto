---
title: Viewing local HTML artifacts in the browser
created: 2026-05-31
updated: 2026-05-31
tags: browser, artifacts, file-protocol, workflow, anti-patterns
scope: system
---

# Viewing local HTML artifacts in the browser

When the agent generates a local HTML file (a report, a render of a notebook, a draft post preview, a dashboard mock) and wants to load it in `browser_navigate`, use the **`file://` URL** to the absolute path. **Do not** spin up an HTTP server with `python3 -m http.server` or similar.

## The right pattern

```
browser_navigate(url="file:///Users/<you>/agents/<co>/workspace/<task>/artifact_index.html")
```

`browser_navigate` accepts `file://` URLs unchanged. The page renders, screenshots work, the agent's vision pipeline can read it, and there's no port to manage or process to clean up.

## Why not `http.server`

Three failure modes observed in production (2026-05-31 cycle on the `browser_task_demo_run` artifact):

1. **Port conflicts.** macOS has services that squat on common ports (`8765 = ultraseek-http`). The agent tried `8765`, failed; tried `8877`, also taken; tried `8989`, started successfully — three shell cycles burned before the server was even up.

2. **Chrome's Private Network Access (PNA) policy blocks the browser even when the server is up.** When the browser is launched with a proxy (residential, datacenter, Tailscale exit), Chrome treats the session as a "public-IP context" and refuses to navigate to private IPs (`127.0.0.1`, `10.x`, `192.168.x`). The visible error is *"Access to 127.0.0.1 was denied"*. The Node bridge ships a workaround (`--disable-features=BlockInsecurePrivateNetworkRequests,...` when proxy is on, [bridge/browser/src/browser-agent.ts](bridge/browser/src/browser-agent.ts)) — but you don't need any of this if you use `file://`.

3. **Process leakage.** A background `python3 -m http.server` keeps running after the agent moves on, holding the port and leaking sockets. The agent rarely cleans it up.

## When `http.server` IS the right call

- The HTML loads JavaScript that does `fetch('/api/...')` to a sibling backend (file:// can't reach localhost via fetch from a file:// origin in most browsers).
- You're testing CORS, CSP, or other origin-scoped behavior that file:// doesn't represent.
- You're loading content that uses absolute-URL imports the file:// origin can't resolve.

In those cases the server is genuinely needed. Pick a non-trivial port (e.g. `8989`, `9876`) to avoid macOS-service collisions, and remember the PNA workaround above is already in place — but **start with `file://` and only fall back when something visibly doesn't work**.

## Path hygiene

- Always use the **absolute** path in the `file://` URL. Relative paths from the agent's CWD are unreliable across the bridge boundary.
- macOS encodes spaces in paths — if the path has spaces, URL-encode them (`%20`) or move the artifact to a space-free workspace dir.
- Symlinks resolve through file:// — the browser will follow them.
