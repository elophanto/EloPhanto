"""Solana on-chain read tools (Helius-backed).

All tools in this group are SAFE — read-only RPC + DAS API queries.
No signing, no transfers, no custody surface. Write-side Solana
operations live in core/payments/manager.py with the spend-limiter
gating them.
"""
