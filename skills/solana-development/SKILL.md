---
name: solana-dev
description: Use when user asks to "build a Solana dapp", "write an Anchor program", "create a token", "debug Solana errors", "set up wallet connection", "test my Solana program", or "deploy to devnet". End-to-end Solana development playbook covering wallet connection, Anchor/Pinocchio programs, Codama client generation, LiteSVM/Mollusk/Surfpool testing, and security checklists. Prefers framework-kit (@solana/client + @solana/react-hooks) for UI, wallet-standard-first connection (incl. ConnectorKit), @solana/kit for client/RPC code, and @solana/web3-compat for legacy boundaries.
user-invocable: true
license: MIT
compatibility: Requires Node.js 18+, Rust toolchain, Solana CLI, Anchor CLI
metadata:
  author: Solana Foundation
  version: 1.1.0
---

# Solana Development Skill (framework-kit-first)

## What this Skill is for
Use this Skill when the user asks for:
- Solana dApp UI work (React / Next.js)
- Wallet connection + signing flows
- Transaction building / sending / confirmation UX
- On-chain program development (Anchor or Pinocchio)
- Client SDK generation (typed program clients)
- Local testing (LiteSVM, Mollusk, Surfpool)
- Security hardening and audit-style reviews
- Confidential transfers (Token-2022 ZK extension)
- **Toolchain setup, version mismatches, GLIBC errors, dependency conflicts**
- **Upgrading Anchor/Solana CLI versions, migration between versions**

## Default stack decisions (opinionated)
1) **UI: framework-kit first**
- Use `@solana/client` + `@solana/react-hooks`.
- Prefer Wallet Standard discovery/connect via the framework-kit client.

2) **SDK: @solana/kit first**
- Prefer Kit types (`Address`, `Signer`, transaction message APIs, codecs).
- Prefer `@solana-program/*` instruction builders over hand-rolled instruction data.

3) **Legacy compatibility: web3.js only at boundaries**
- If you must integrate a library that expects web3.js objects (`PublicKey`, `Transaction`, `Connection`),
  use `@solana/web3-compat` as the boundary adapter.
- Do not let web3.js types leak across the entire app; contain them to adapter modules.

4) **Programs**
- Default: Anchor (fast iteration, IDL generation, mature tooling).
- Performance/footprint: Pinocchio when you need CU optimization, minimal binary size,
  zero dependencies, or fine-grained control over parsing/allocations.

5) **Testing**
- Default: LiteSVM or Mollusk for unit tests (fast feedback, runs in-process).
- Use Surfpool for integration tests against realistic cluster state (mainnet/devnet) locally.
- Use solana-test-validator only when you need specific RPC behaviors not emulated by LiteSVM.

## Operating procedure (how to execute tasks)
When solving a Solana task:

### 1. Classify the task layer
- UI/wallet/hook layer
- Client SDK/scripts layer
- Program layer (+ IDL)
- Testing/CI layer
- Infra (RPC/indexing/monitoring)

### 2. Pick the right building blocks
- UI: framework-kit patterns.
- Scripts/backends: @solana/kit directly.
- Legacy library present: introduce a web3-compat adapter boundary.
- High-performance programs: Pinocchio over Anchor.

### 3. Implement with Solana-specific correctness
Always be explicit about:
- cluster + RPC endpoints + websocket endpoints
- fee payer + recent blockhash
- compute budget + prioritization (where relevant)
- expected account owners + signers + writability
- token program variant (SPL Token vs Token-2022) and any extensions

### 4. Add tests
- Unit test: LiteSVM or Mollusk.
- Integration test: Surfpool.
- For "wallet UX", add mocked hook/provider tests where appropriate.

### 5. Deliverables expectations
When you implement changes, provide:
- exact files changed + diffs (or patch-style output)
- commands to install/build/test
- a short "risk notes" section for anything touching signing/fees/CPIs/token transfers

## Progressive disclosure (read when needed)
- UI + wallet + hooks: [frontend-framework-kit.md](references/frontend-framework-kit.md)
- Kit ↔ web3.js boundary: [kit-web3-interop.md](references/kit-web3-interop.md)
- Anchor programs: [programs-anchor.md](references/programs-anchor.md)
- Pinocchio programs: [programs-pinocchio.md](references/programs-pinocchio.md)
- Testing strategy: [testing.md](references/testing.md)
- IDLs + codegen: [idl-codegen.md](references/idl-codegen.md)
- Payments: [payments.md](references/payments.md)
- Confidential transfers: [confidential-transfers.md](references/confidential-transfers.md)
- Security checklist: [security.md](references/security.md)
- Reference links: [resources.md](references/resources.md)
- **Version compatibility:** [compatibility-matrix.md](references/compatibility-matrix.md)
- **Common errors & fixes:** [common-errors.md](references/common-errors.md)
- **Surfpool (local network):** [surfpool.md](references/surfpool.md)
- **Surfpool cheatcodes:** [surfpool-cheatcodes.md](references/surfpool-cheatcodes.md)
