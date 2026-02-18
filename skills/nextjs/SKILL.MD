---
name: nextjs16-skills
description: Key facts and links for Next.js 16. Use for planning, writing, and troubleshooting Next.js 16 changes.
---

## Links

- Docs: https://nextjs.org/docs
- Upgrade guide (v16): https://nextjs.org/docs/app/guides/upgrading/version-16
- Release notes/blog: https://nextjs.org/blog/next-16

## Upgrade

```sh
# Automated upgrade
npx @next/codemod@canary upgrade latest

# Manual upgrade
npm install next@latest react@latest react-dom@latest

# New project
npx create-next-app@latest
```

Codemod covers (high-level): moves Turbopack config, migrates `next lint` → ESLint CLI, migrates `middleware` → `proxy`, removes some `unstable_` prefixes, removes route-level `experimental_ppr`.

TypeScript: also upgrade `@types/react` and `@types/react-dom`.

## What’s New (v16)

- Cache Components: opt-in caching via the `"use cache"` directive; evolves/absorbs PPR.
- Next.js DevTools MCP: Model Context Protocol integration for AI-assisted debugging.
- `proxy.ts`: clearer network boundary; `middleware.ts` deprecated for most use.
- Better logs/metrics: more detailed `next dev` and build timing output.

## Performance / DX

- Turbopack: stable; default bundler (opt out with `next dev --webpack`, `next build --webpack`).
- If you have a custom `webpack` config, `next build` may fail (to prevent misconfiguration). Fix by migrating config, using `next build --webpack`, or using Turbopack and removing/ignoring the webpack config.
- Turbopack config moved: `experimental.turbopack` → top-level `turbopack` in `next.config.*`.
- Turbopack migration gotchas:
	- Sass imports: remove the Webpack-only `~` prefix (e.g. `@import 'bootstrap/...';`).
	- Browser bundles must not import Node built-ins (e.g. `fs`). If unavoidable, use `turbopack.resolveAlias` as a stopgap.
- Turbopack filesystem cache (dev, beta): `experimental.turbopackFileSystemCacheForDev: true`.
- React Compiler support: stable opt-in via `reactCompiler: true` (expect higher build/compile cost).
- Build Adapters API: alpha (custom build adapters).
- Routing/prefetching rewrite: layout deduplication + incremental prefetching.

## Caching APIs (key signatures)

- `revalidateTag(tag, profile)` now requires a cacheLife profile (or `{ expire }`) for SWR behavior.
- `updateTag(tag)` (Server Actions only): read-your-writes semantics.
- `refresh()` (Server Actions only): refresh uncached data; does not mutate cache.
- `cacheLife` and `cacheTag` are stable (no `unstable_` prefix).

## Requirements (v16)

- Node.js: 20.9+ (Node 18 not supported)
- TypeScript: 5.1+
- Browsers: Chrome/Edge/Firefox 111+, Safari 16.4+

## Breaking / Behavior Changes (high-impact)

- Async Request APIs: sync access removed. Use `await params`, `await searchParams`, `await cookies()`, `await headers()`, `await draftMode()`.
- Tip (TypeScript): `npx next typegen` can generate helpers like `PageProps`, `LayoutProps`, `RouteContext` to migrate `params/searchParams` types safely.
- Metadata images: `opengraph-image`, `twitter-image`, `icon`, `apple-icon` now receive `params` (and `id`) as Promises in the image function.
- Sitemaps: `sitemap({ id })` now receives `id` as a Promise when using `generateSitemaps`.
- Parallel routes: slots require explicit `default.js`.
- `next/image` defaults changed (cache TTL, sizes/qualities); local `src` with query strings requires `images.localPatterns`.

Other notable behavior changes:

- `next dev` and `next build` use separate output dirs (`next dev` → `.next/dev`) and a lockfile prevents concurrent instances.
- Scroll behavior: Next.js no longer overrides global `scroll-behavior: smooth` during navigations; add `data-scroll-behavior="smooth"` on `<html>` to restore the previous override behavior.
- ESLint: `@next/eslint-plugin-next` defaults to ESLint Flat Config; legacy `.eslintrc` projects may need migration.

## Removed / Deprecated (high-level)

- Removed: AMP support; `next lint` (use ESLint/Biome directly); `eslint` option in `next.config.*`; `serverRuntimeConfig/publicRuntimeConfig` (use env vars); `experimental.ppr` + route-level `experimental_ppr`; `unstable_rootParams`.
- Deprecated: `middleware.ts` filename (prefer `proxy.ts`); `next/legacy/image`; `images.domains` (prefer `images.remotePatterns`); `revalidateTag(tag)` single-arg form.
- `proxy.ts` note: `proxy` runs on `nodejs` only; Edge runtime is not supported in `proxy`. Keep `middleware.ts` if you must stay on Edge.
- Config rename example: `skipMiddlewareUrlNormalize` → `skipProxyUrlNormalize`.
