---
title: EloPhanto Style Guide
created: 2026-03-10
updated: 2026-03-10
tags: brand, design, visual, style, ui
scope: system
covers: [web-dashboard/src/**/*.tsx, vscode-extension/src/**/*.ts]
---

# EloPhanto Style Guide

> Visual and brand identity reference. Use when building UIs, landing pages,
> marketing materials, or social content. Keeps everything consistent.
> Inspired by [Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184).

---

## Brand Identity

**Name**: EloPhanto (capital E, capital P, one word)
**Tagline**: "A self-evolving AI agent that lives on your machine."
**Repo**: https://github.com/elophanto/EloPhanto
**Website**: https://elophanto.com

**Personality**: Technical but approachable. Confident but not arrogant. Shows, doesn't tell. First-person when speaking as the agent. Concrete proof over abstract claims.

---

## Color Palette

### Dark Theme (Primary)

| Role | Color | Hex | Usage |
|------|-------|-----|-------|
| Background | Near-black | `#0a0a0a` | Page background, panels |
| Surface | Dark grey | `#141414` | Cards, sidebar, elevated surfaces |
| Border | Subtle grey | `#262626` | Dividers, card borders |
| Text primary | White | `#fafafa` | Headings, body text |
| Text secondary | Muted grey | `#a1a1aa` | Labels, descriptions, timestamps |
| Accent | Electric purple | `#8b5cf6` | CTAs, links, highlights, active states |
| Accent hover | Lighter purple | `#a78bfa` | Hover states |
| Success | Green | `#22c55e` | Positive states, "connected", safe tools |
| Warning | Amber | `#f59e0b` | Moderate risk, attention needed |
| Danger | Red | `#ef4444` | Destructive actions, critical tools, errors |

### Light Theme (Secondary)

Invert: white background (`#fafafa`), dark text (`#0a0a0a`), same accent purple. Surface becomes `#f4f4f5`.

### CLI Colors

The terminal UI uses Rich with a monochrome gradient: `grey35` → `grey50` → `grey70` → `bright_white` for the ASCII banner. Risk-colored approval panels: green (safe), yellow (moderate), red (destructive/critical).

---

## Typography

| Role | Font | Fallback | Weight |
|------|------|----------|--------|
| Headings | Geist Mono | `monospace` | 600 (semibold) |
| Body | Inter | `system-ui, sans-serif` | 400 (regular) |
| Code | JetBrains Mono | `monospace` | 400 |
| UI labels | Inter | `system-ui, sans-serif` | 500 (medium) |

- Headings use monospace for the technical/hacker aesthetic
- Body uses clean sans-serif for readability
- Code blocks always monospace with copy buttons

---

## Component Patterns

### Cards
- Dark surface background with subtle border
- Rounded corners (`border-radius: 8px`)
- No drop shadows (flat design, borders only)
- Hover: slightly lighter background or accent border

### Terminal/Code Blocks
- Near-black background (`#0a0a0a`)
- Green or white text on dark
- Copy button in top-right corner
- Language label in top-left
- Syntax highlighting via Shiki or Prism

### Stat Strips
- Horizontal row of key metrics
- Monospace numbers, label below
- Example: **147 skills** · **140+ tools** · **6 channels**

### Feature Grids
- 2-3 column card grid
- Icon + title + short description per card
- Lucide icons, consistent size

### Status Indicators
- Connected: green dot + "Connected"
- Disconnected: grey dot + "Disconnected"
- Thinking: pulse animation on dot
- Tool execution: bouncing bar spinner

---

## Tone of Voice

### Do
- Write in first person when speaking as the agent ("I built 147 tools")
- Be specific and concrete ("Swap SOL→USDC in one message" not "AI-powered DeFi")
- Show technical depth without jargon walls
- Use short, punchy sentences for social media
- Lead with what it does, not what it is

### Don't
- Use "AI-powered" or "leveraging AI" — everyone says this
- Use emojis unless the user explicitly requests them
- Use corporate buzzwords ("synergy", "ecosystem play", "paradigm shift")
- Overclaim ("the most advanced agent ever built")
- Sound desperate ("please star our repo!")

### Social Media Style
- **Hook**: Scroll-stopping first line — concrete, surprising, or contrarian
- **Body**: 2-4 sentences of substance — what, how, proof
- **CTA**: Single clear action — link, try it, star it
- No hashtag spam. Max 1-2 if the platform benefits from them.

### Examples

Good: "I built an agent that swaps tokens on Jupiter while you sleep. Self-custody, local-first, 147 skills. github.com/elophanto/EloPhanto"

Bad: "Excited to announce our AI-powered blockchain agent! 🚀🔥 Leveraging cutting-edge LLMs for seamless DeFi integration. #AI #Crypto #Web3 #Solana"

---

## Layout Patterns

### Landing Page
```
[Hero: tagline + install snippet + CTAs]
[Feature grid: 14 cards in 3-column layout]
[Stats strip: skills · tools · channels · docs]
[Architecture diagram: simplified ASCII]
[Getting started: 3 steps]
[Footer: links, GitHub, social]
```

### Dashboard
```
[Sidebar: nav items with icons, logo at top]
[Main area: context-dependent content]
[Header: page title + breadcrumbs]
```

### Documentation
```
[Left sidebar: grouped navigation]
[Center: rendered markdown content]
[Right: table of contents (optional)]
```

---

## Iconography

Use **Lucide** icons throughout. Consistent 20px size for inline, 24px for nav, 16px for badges.

Key icons:
- Terminal → `terminal`
- Browser → `globe`
- Wallet → `wallet`
- Skills → `sparkles`
- Knowledge → `book-open`
- Mind → `brain`
- Security → `shield`
- Settings → `settings`
- Channels → `radio`

---

## Anti-Patterns

- No stock photos or generic AI imagery (robots, glowing brains)
- No gradient backgrounds (flat dark surfaces only)
- No heavy animations or parallax scrolling
- No cookie banners or newsletter popups on first visit
- No "powered by" badges from third parties
- No light mode as default — dark first, light as toggle
