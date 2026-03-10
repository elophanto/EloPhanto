# EloPhanto — Solana Ecosystem Integration

> **Status: Phase 1 + Swaps Done** — Native Solana wallet (self-custody, auto-create, SOL + USDC transfers) + DEX swaps via Jupiter Ultra API. Phase 2: DeFi via skills + MCP servers. Phase 3: Agent economy (staking, identity, commerce).

## Overview

EloPhanto has native Solana chain support with a self-custody wallet. This doc covers the broader Solana AI ecosystem and the integration roadmap — skills, MCP servers, agent toolkits, and protocols that extend EloPhanto's capabilities on Solana.

Based on the [Awesome Solana AI](https://github.com/solana-foundation/awesome-solana-ai) registry (62 projects).

## Current State

| Capability | Status |
|-----------|--------|
| Solana wallet (self-custody) | Done — `solders` + `base58`, auto-create keypair |
| SOL transfers | Done — system program transfer |
| SPL token transfers (USDC) | Done — instruction type 3 + ATA derivation |
| Wallet export (Phantom/Solflare) | Done — `wallet_export` tool, base58 private key |
| Startup banner wallet display | Done — shows address + chain |
| DEX swaps | Done — Jupiter Ultra API (`/ultra/v1/order` → sign → `/ultra/v1/execute`) |
| DeFi (lending, staking, perps) | Not yet — planned via skills |
| NFTs | Not yet — planned via Metaplex skill |
| On-chain agent identity | Not yet — planned via SAID Protocol |

## Integration Roadmap

### Phase 2: Skills + MCP Servers

The Solana AI ecosystem has a rich set of SKILL.md-format skills and MCP servers that plug directly into EloPhanto's existing infrastructure.

#### MCP Servers (plug-and-play)

These connect via EloPhanto's MCP system (`mcp_manage` tool) with zero custom code:

| Server | What It Does | Install |
|--------|-------------|---------|
| **[Solana Developer MCP](https://mcp.solana.com/)** | Official Solana + Anchor docs in IDE context. Maintained by Solana Foundation | `mcp_manage add solana-dev` |
| **[QuickNode MCP](https://www.npmjs.com/package/@quicknode/mcp)** | Provision/manage blockchain infra, Solana RPC, Jupiter API, gRPC streams via natural language | `mcp_manage add quicknode` |
| **[DFlow MCP](https://pond.dflow.net/build/mcp)** | Spot + prediction market trading API with smart routing and low-failure execution | `mcp_manage add dflow` |
| **[Deside MCP](https://github.com/DesideApp/deside-mcp)** | Wallet-to-wallet messaging for agents. Ed25519 keypair auth — uses our existing Solana keypair | `mcp_manage add deside` |

**Priority:** Solana Developer MCP first (official, zero risk), then QuickNode MCP for better RPC.

#### Skills (install into EloPhantoHub)

All SKILL.md format — compatible with `hub_install` or manual placement in `skills/`:

**Solana Development (7 skills)**

| Skill | Source | What It Teaches |
|-------|--------|----------------|
| **solana-dev-skill** | [Solana Foundation](https://github.com/solana-foundation/solana-dev-skill) | Official — wallet connections, Anchor/Pinocchio programs, testing with LiteSVM/Mollusk, security best practices |
| **solana-anchor-claude-skill** | [QuickNode](https://github.com/quiknode-labs/solana-anchor-claude-skill) | Anchor + Solana Kit, modern minimal code, native test runners, LiteSVM |
| **solana-game-skill** | [SolanaBR](https://github.com/solanabr/solana-game-skill) | Game dev — C#, React Native, MagicBlock Unity SDK, Solana Mobile |
| **magicblock-dev-skill** | [MagicBlock](https://github.com/magicblock-labs/magicblock-dev-skill) | On-chain games, session keys, VRFs, cranks, Solana network extensions |
| **solana-kit-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/solana-kit) | Modern @solana/kit — tree-shakeable, zero-dependency JS SDK from Anza |
| **solana-kit-migration-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/solana-kit-migration) | Migrate from @solana/web3.js v1.x to @solana/kit with API mappings |
| **pinocchio-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/pinocchio-development) | Zero-copy framework for high-perf Solana programs (88-95% CU reduction) |

**DeFi (16 skills)**

| Skill | Protocol | What It Covers |
|-------|----------|---------------|
| **jupiter-skill** | [Jupiter](https://github.com/jup-ag/agent-skills/tree/main/skills/integrating-jupiter) | Ultra swaps, limit orders, DCA, perpetuals, lending, token APIs |
| **drift-skill** | [Drift](https://github.com/sendaifun/skills/tree/main/skills/drift) | Perpetual futures, spot trading, DeFi applications |
| **raydium-skill** | [Raydium](https://github.com/sendaifun/skills/tree/main/skills/raydium) | CLMM/CPMM pools, LaunchLab token launches, farming, Trade API |
| **orca-skill** | [Orca](https://github.com/sendaifun/skills/tree/main/skills/orca) | Whirlpools concentrated liquidity — swaps, pool creation, position management |
| **meteora-skill** | [Meteora](https://github.com/sendaifun/skills/tree/main/skills/meteora) | AMMs, bonding curves, vaults, token launches |
| **kamino-skill** | [Kamino](https://github.com/sendaifun/skills/tree/main/skills/kamino) | Lending, borrowing, liquidity management, leverage trading, oracle aggregation |
| **lulo-skill** | [Lulo](https://github.com/sendaifun/skills/tree/main/skills/lulo) | Lending aggregator — routes deposits to highest yield across Kamino, Drift, MarginFi, Jupiter |
| **sanctum-skill** | [Sanctum](https://github.com/sendaifun/skills/tree/main/skills/sanctum) | Liquid staking, LST swaps, Infinity pool operations |
| **pumpfun-skill** | [PumpFun](https://github.com/sendaifun/skills/tree/main/skills/pumpfun) | Token launches, bonding curves, PumpSwap AMM |
| **dflow-skill** | [DFlow](https://github.com/sendaifun/skills/tree/main/skills/dflow) | Spot trading, prediction markets, Swap API, WebSocket streaming |
| **dflow-phantom-connect-skill** | [DFlow](https://github.com/DFlowProtocol/dflow_phantom-connect-skill) | Full-stack wallet-connected Solana apps with Phantom Connect, DFlow swaps, Proof KYC |
| **ranger-finance-skill** | [Ranger](https://github.com/sendaifun/skills/tree/main/skills/ranger-finance) | Perps aggregator across Drift, Flash, Adrena, Jupiter |
| **octav-api-skill** | [Octav](https://github.com/Octav-Labs/octav-api-skill) | Portfolio tracking, transaction history, DeFi positions, token analytics |
| **clawpump-skill** | [ClawPump](https://www.clawpump.tech/skill.md) | Gasless token launches on pump.fun, 65% trading fee revenue share |
| **clawpump-arbitrage-skill** | [ClawPump](https://clawpump.tech/arbitrage.md) | Multi-DEX arbitrage — 11 DEX quotes, roundtrip/bridge strategies, tx bundle generation |
| **pnp-markets-skill** | [PNP Protocol](https://github.com/pnp-protocol/solana-skill) | Permissionless prediction markets — V2 AMM, P2P betting, custom oracle settlement |

**Infrastructure (10 skills)**

| Skill | Protocol | What It Covers |
|-------|----------|---------------|
| **helius-skill** | [Helius](https://github.com/sendaifun/skills/tree/main/skills/helius) | RPC, DAS API, Enhanced Transactions, Priority Fees, Webhooks, LaserStream gRPC |
| **metaplex-skill** | [Metaplex](https://github.com/metaplex-foundation/skill) | Official — Core NFTs, Token Metadata, Bubblegum, Candy Machine, Genesis launches, Umi/Kit SDKs |
| **metaplex-skill (community)** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/metaplex) | Community version — Core NFTs, Token Metadata, Bubblegum, Candy Machine, Umi framework |
| **light-protocol-skill** | [Light Protocol](https://github.com/sendaifun/skills/tree/main/skills/light-protocol) | ZK Compression — rent-free compressed tokens and PDAs using zero-knowledge proofs |
| **pyth-skill** | [Pyth](https://github.com/sendaifun/skills/tree/main/skills/pyth) | Oracle — real-time price feeds with confidence intervals and EMA prices |
| **switchboard-skill** | [Switchboard](https://github.com/sendaifun/skills/tree/main/skills/switchboard) | Oracle — permissionless price feeds, on-demand data, VRF randomness, Surge streaming |
| **squads-skill** | [Squads](https://github.com/sendaifun/skills/tree/main/skills/squads) | Multisig wallets, smart accounts, account abstraction |
| **debridge-skill** | [deBridge](https://github.com/sendaifun/skills/tree/main/skills/debridge) | Cross-chain bridges — Solana <-> EVM token transfers and message passing |
| **coingecko-skill** | [CoinGecko](https://github.com/sendaifun/skills/tree/main/skills/coingecko) | Token prices, DEX pool data, OHLCV charts, market analytics |
| **quicknode-blockchain-skills** | [QuickNode](https://github.com/quiknode-labs/blockchain-skills) | RPC infrastructure, Jupiter Swap API, Yellowstone gRPC streams |

**Security (3 skills)**

| Skill | Source | What It Covers |
|-------|--------|---------------|
| **solana-skills-plugin** | [tenequm](https://github.com/tenequm/claude-plugins/tree/main/solana) | Program development, security auditing with vulnerability detection, ZK compression |
| **vulnhunter-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/vulnhunter) | Security vulnerability detection, dangerous API hunting, variant analysis |
| **code-recon-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/zz-code-recon) | Deep architectural context building for security audits, trust boundary mapping |

**Dev Tools (2 skills)**

| Skill | Source | What It Covers |
|-------|--------|---------------|
| **surfpool-skill** | [sendaifun](https://github.com/sendaifun/skills/tree/main/skills/surfpool) | Solana dev environment with mainnet forking, cheatcodes, Infrastructure as Code |
| **solana-dev-skill-rent-free** | [Light Protocol](https://github.com/Lightprotocol/skills) | Rent-free development patterns for DeFi, payments, token distribution, ZK programs |

### Phase 3: Agent Economy

#### Agent Toolkits

| Toolkit | What It Does | Integration Path |
|---------|-------------|-----------------|
| **[Solana Agent Kit](https://github.com/sendaifun/solana-agent-kit)** | 50+ actions across 30+ protocols — token ops, NFTs, swaps, DeFi. Works with LangChain, Eliza, Vercel AI SDK | Python wrapper or direct protocol calls |
| **[GOAT Framework](https://github.com/goat-sdk/goat)** | 200+ on-chain tools, multi-chain (Solana + EVM) | Plugin or MCP adapter |
| **[LumoKit](https://github.com/Lumo-Labs-AI/lumokit)** | Lightweight Python toolkit — on-chain actions, Jupiter swaps, research tools | Direct Python integration (closest to our stack) |
| **[Breeze Agent Kit](https://github.com/anagrambuild/breeze-agent-kit)** | Yield farming automation via Breeze protocol, MCP server included | MCP server or direct integration |
| **[Eliza Framework](https://github.com/elizaOS/eliza)** | Lightweight TypeScript agent framework with Solana integrations | Reference for patterns, not direct integration |

#### Agent Identity & Reputation

| Protocol | What It Does | Why It Matters |
|----------|-------------|---------------|
| **[SAID Protocol](https://saidprotocol.com)** | On-chain agent identity + reputation + verification on Solana. Public agent directory | Complements EloPhanto's identity system — gives the agent a verifiable on-chain presence |
| **[SATI](https://github.com/cascade-protocol/sati)** | ERC-8004 compliant agent identity with proof-of-participation | Cross-chain identity standard |
| **[CYNIC](https://github.com/zeyxx/CYNIC)** | Decentralized collective consciousness — 11 agents, Proof of Judgment, on-chain reputation | Research reference for multi-agent coordination |

#### Agent Commerce

| Project | What It Does | Why It Matters |
|---------|-------------|---------------|
| **[SP3ND](https://github.com/kent-x1/sp3nd-agent-skill)** | Buy real products from Amazon with USDC on Solana. No KYC, free Prime shipping, 200+ countries | Agent can purchase physical goods autonomously |
| **[OpenDexter](https://open.dexter.cash)** | Search 5,000+ paid APIs, automatic USDC settlement. Available as MCP server | Agent can discover and pay for API access autonomously |
| **[QuickNode x402](https://www.quicknode.com/docs/build-with-ai/x402-payments)** | Pay-per-request RPC access with USDC — no signup, no API keys | Truly autonomous infrastructure access |
| **[Solentic](https://github.com/mbrassey/solentic)** | Native Solana staking — 18 MCP tools, 21 REST endpoints, ~6% APY | Passive income for idle SOL in agent wallet |

#### On-Chain AI

| Project | What It Does |
|---------|-------------|
| **[SLO (Solana LLM Oracle)](https://github.com/GauravBurande/solana-llm-oracle)** | LLM inference directly in Solana programs — on-chain AI for games and protocols |
| **[Sentients](https://github.com/koshmade/sentients.wtf)** | AI agents minting unique inscriptions on Solana with deterministic art from blockchain entropy |
| **[Chronoeffector AI Arena](https://arena.chronoeffector.ai)** | Autonomous AI agent trading arena on Solana — crypto, stocks, commodities, prediction markets |
| **[Splatworld](https://splatworld.io)** | Agent social platform — AI agents collaborate and vote to generate 3D gaussian splat metaverse worlds |

#### AI-Powered Dev Tools

| Tool | What It Does |
|------|-------------|
| **[AImpact](https://aimpact.dev)** | Online AI IDE for Web3 — generate and deploy Solana smart contracts |
| **[Exo AI Audits](https://ai-audits.exotechnologies.xyz)** | AI-powered smart contract auditing for Solana programs |

## Recommended Installation Order

### Week 1: Foundation
1. Install **Solana Developer MCP** — official docs in context, zero risk
2. Install **solana-dev-skill** — official Solana Foundation development skill
3. Install **helius-skill** — better RPC knowledge for the agent

### Week 2: DeFi
4. Install **jupiter-skill** — unlocks swap knowledge (code integration for `crypto_swap` follows)
5. Install **metaplex-skill** — NFT capabilities
6. Install **coingecko-skill** — market data and analytics
7. Install **QuickNode MCP** — managed RPC infrastructure

### Week 3: Advanced DeFi
8. Install **drift-skill** + **kamino-skill** — perps and lending
9. Install **lulo-skill** — yield optimization
10. Install **sanctum-skill** — liquid staking

### Week 4: Agent Economy
11. Integrate **LumoKit** — Python-native toolkit for direct Solana actions
12. Explore **SP3ND** — real-world purchases with USDC
13. Explore **SAID Protocol** — on-chain agent identity
14. Explore **Solentic** — passive staking income

## Architecture: How Skills + MCP Extend the Wallet

```
Current (Phase 1 + Swaps):
    Agent → solana_wallet.py → JSON-RPC → Solana
    (SOL transfers, USDC transfers)
    Agent → crypto_swap tool → manager.py → solana_wallet.jupiter_swap()
        → GET /ultra/v1/order → sign with solders → POST /ultra/v1/execute
    (Any token pair via Jupiter aggregator)

Phase 2 (Skills + MCP):
    Agent → Solana Developer MCP → accurate docs for program development
    Agent → QuickNode MCP → managed RPC, gRPC streams, Jupiter API

Phase 3 (Agent Economy):
    Agent → SP3ND skill → buy products with USDC
    Agent → OpenDexter MCP → discover + pay for APIs
    Agent → Solentic MCP → stake SOL for passive yield
    Agent → SAID Protocol → register on-chain identity
```

The wallet (`core/payments/solana_wallet.py`) handles signing and sending. Skills teach the agent how to construct transactions for specific protocols. MCP servers provide real-time data and infrastructure access.

## Related Docs

- [15-PAYMENTS.md](15-PAYMENTS.md) — Wallet setup, spending limits, approval flows
- [23-MCP.md](23-MCP.md) — MCP server integration
- [13-SKILLS.md](13-SKILLS.md) — Skill system and EloPhantoHub
- [17-IDENTITY.md](17-IDENTITY.md) — Agent identity (relevant for SAID Protocol)
