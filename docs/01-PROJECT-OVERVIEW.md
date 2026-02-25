# EloPhanto — Project Overview

## What Is EloPhanto?

EloPhanto is an open-source, self-evolving AI agent that acts as a personal AI operating system. It runs locally on the user's machine with full system access — filesystem, shell, browser, email, and more — and can autonomously develop new capabilities when it encounters tasks it cannot yet handle.

It is not a chatbot. It is not an assistant wrapper. It is a persistent, self-aware agent that knows its own architecture, maintains its own documentation, writes and tests its own code, and grows more capable over time.

## Core Principles

- **Local-first**: Runs on the user's machine. No central server dependency. All data stays local unless the user opts into sync.
- **Self-evolving**: When EloPhanto encounters a task it lacks tools for, it designs, implements, tests, and deploys a new plugin — then documents what it built.
- **Self-aware**: EloPhanto maintains markdown documentation of its own architecture, capabilities, and changelog. It reads these files on startup to understand itself.
- **Full system access**: Shell, filesystem, real browser (with user's sessions), email, calendar — anything the user can do, EloPhanto can do.
- **Open source**: Apache 2.0 licensed. No telemetry. No central server. No vendor lock-in.
- **Secure by design**: Encrypted credential vault. Immutable permission core. Tiered approval system.
- **Autonomous when idle**: Between user interactions, a purpose-driven background mind pursues goals, revenue, and maintenance on its own. Pauses when you speak, resumes when done. Budget-isolated.

## What Makes It Different

Most AI agents are sandboxed tools that call APIs. EloPhanto is different in three ways:

1. **Real browser control** — It controls a real Chrome browser via a Node.js bridge to a battle-tested TypeScript browser engine (Playwright + stealth). In profile mode, it inherits the user's logged-in sessions. No re-authentication needed. It sees what the user sees.
2. **Self-development with QA** — It doesn't just write code. It follows a full development pipeline: research → design → implement → test → review → deploy → monitor. Every self-created plugin includes unit tests, integration tests, and documentation.
3. **Persistent self-awareness** — It knows what it is, what it can do, what it has built, and what has failed. This knowledge persists across sessions in structured markdown files that both the agent and the user can read and edit.

## Target Users

- Developers and technical users who want an AI agent with real system access
- Power users who want to automate complex workflows across multiple services
- Anyone who wants an AI that gets smarter and more capable the more they use it

## Project Identity

- **Name**: EloPhanto
- **Domain**: elophanto.com
- **License**: Apache 2.0
- **Language**: Python (agent core) + TypeScript (Node.js browser bridge + React web dashboard)
- **Repository**: To be created on GitHub
