"""Payment request lifecycle: create, check, expire, cancel."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

_SOLANA_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Known token mints for Solana Pay URIs
_SOLANA_TOKEN_MINTS: dict[str, str] = {
    "USDC": _SOLANA_USDC_MINT,
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

# Known ERC-20 contract addresses (Base mainnet)
_EVM_TOKEN_CONTRACTS: dict[str, dict[str, str]] = {
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    },
}

_CHAIN_IDS: dict[str, int] = {
    "base": 8453,
    "ethereum": 1,
    "polygon": 137,
    "arbitrum": 42161,
}


class PaymentRequestTracker:
    """Manages payment request lifecycle: create, check, expire, cancel."""

    def __init__(self, db: Any, auditor: Any) -> None:
        self._db = db
        self._auditor = auditor

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_request(
        self,
        *,
        wallet_address: str,
        chain: str,
        token: str,
        amount: float,
        memo: str | None = None,
        ttl_minutes: int = 60,
        session_id: str | None = None,
        channel: str | None = None,
        task_context: str | None = None,
    ) -> dict[str, Any]:
        """Create a new payment request. Returns request details."""
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        reference = f"ref_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=ttl_minutes)

        await self._db.execute_insert(
            "INSERT INTO payment_requests "
            "(request_id, wallet_address, chain, token, amount, memo, reference, "
            "status, created_at, expires_at, session_id, channel, task_context) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
            (
                request_id,
                wallet_address,
                chain,
                token,
                amount,
                memo,
                reference,
                now.isoformat(),
                expires_at.isoformat(),
                session_id,
                channel,
                task_context,
            ),
        )

        # Audit
        await self._auditor.log(
            tool_name="payment_request",
            amount=amount,
            currency=token,
            recipient=wallet_address,
            payment_type="request",
            chain=chain,
            status="pending",
            session_id=session_id,
            channel=channel,
            task_context=task_context,
        )

        payment_link = self.format_payment_link(
            chain, wallet_address, token, amount, reference, memo
        )

        return {
            "request_id": request_id,
            "wallet_address": wallet_address,
            "chain": chain,
            "token": token,
            "amount": amount,
            "memo": memo,
            "reference": reference,
            "payment_link": payment_link,
            "expires_at": expires_at.isoformat(),
            "status": "pending",
        }

    # ------------------------------------------------------------------
    # Check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        request_id: str,
        wallet_provider: Any,
        chain: str,
    ) -> dict[str, Any]:
        """Check if a pending request has been fulfilled on-chain."""
        req = await self.get_request(request_id)
        if not req:
            return {"error": f"Request {request_id} not found"}

        if req["status"] != "pending":
            return req

        # Check expiry
        expires_at = datetime.fromisoformat(req["expires_at"])
        if datetime.now(UTC) > expires_at:
            await self._db.execute(
                "UPDATE payment_requests SET status = 'expired' WHERE request_id = ?",
                (request_id,),
            )
            req["status"] = "expired"
            return req

        # Scan blockchain
        try:
            created_at = datetime.fromisoformat(req["created_at"])
            txs = wallet_provider.get_incoming_transactions(
                since_timestamp=created_at.timestamp(),
                token_filter=req["token"],
            )
        except Exception as exc:
            return {**req, "scan_error": str(exc)}

        # Match by amount (0.1% tolerance)
        target = req["amount"]
        for tx in txs:
            tx_amount = tx.get("amount", 0)
            if abs(tx_amount - target) / max(target, 0.001) < 0.001:
                # Match found
                paid_at = datetime.now(UTC).isoformat()
                await self._db.execute(
                    "UPDATE payment_requests SET status = 'paid', "
                    "matching_tx_hash = ?, matching_amount = ?, "
                    "matching_sender = ?, paid_at = ? "
                    "WHERE request_id = ?",
                    (
                        tx.get("tx_hash", ""),
                        tx_amount,
                        tx.get("from_address", ""),
                        paid_at,
                        request_id,
                    ),
                )
                return {
                    **req,
                    "status": "paid",
                    "matching_tx_hash": tx.get("tx_hash", ""),
                    "matching_amount": tx_amount,
                    "matching_sender": tx.get("from_address", ""),
                    "paid_at": paid_at,
                }

        return {**req, "scanned_txs": len(txs)}

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Fetch a single request by ID."""
        rows = await self._db.fetch_all(
            "SELECT * FROM payment_requests WHERE request_id = ?",
            (request_id,),
        )
        if not rows:
            return None
        row = rows[0]
        cols = [
            "request_id",
            "wallet_address",
            "chain",
            "token",
            "amount",
            "memo",
            "reference",
            "status",
            "matching_tx_hash",
            "matching_amount",
            "matching_sender",
            "created_at",
            "expires_at",
            "paid_at",
            "session_id",
            "channel",
            "task_context",
        ]
        return dict(zip(cols, row))

    async def list_requests(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List payment requests, optionally filtered by status."""
        if status:
            rows = await self._db.fetch_all(
                "SELECT * FROM payment_requests WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM payment_requests ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        cols = [
            "request_id",
            "wallet_address",
            "chain",
            "token",
            "amount",
            "memo",
            "reference",
            "status",
            "matching_tx_hash",
            "matching_amount",
            "matching_sender",
            "created_at",
            "expires_at",
            "paid_at",
            "session_id",
            "channel",
            "task_context",
        ]
        return [dict(zip(cols, row)) for row in rows]

    # ------------------------------------------------------------------
    # Cancel / Expire
    # ------------------------------------------------------------------

    async def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending request."""
        req = await self.get_request(request_id)
        if not req or req["status"] != "pending":
            return False
        await self._db.execute(
            "UPDATE payment_requests SET status = 'cancelled' WHERE request_id = ?",
            (request_id,),
        )
        return True

    async def expire_stale_requests(self) -> int:
        """Mark all past-due pending requests as expired. Returns count."""
        now = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "UPDATE payment_requests SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at < ?",
            (now,),
        )
        return cursor.rowcount if hasattr(cursor, "rowcount") else 0

    # ------------------------------------------------------------------
    # Payment Links
    # ------------------------------------------------------------------

    def format_payment_link(
        self,
        chain: str,
        address: str,
        token: str,
        amount: float,
        reference: str | None = None,
        memo: str | None = None,
    ) -> str:
        """Generate a shareable payment link/URI."""
        token_upper = token.upper()

        if chain in ("solana", "solana-devnet"):
            # Solana Pay URI: solana:<address>?amount=<amount>&spl-token=<mint>
            parts = [f"solana:{address}?amount={amount}"]
            mint = _SOLANA_TOKEN_MINTS.get(token_upper)
            if mint:
                parts.append(f"spl-token={mint}")
            if reference:
                parts.append(f"reference={reference}")
            if memo:
                parts.append(f"memo={memo}")
            return "&".join(parts)

        # EVM: ethereum:<token>@<chainId>/transfer?address=<to>&uint256=<amount>
        chain_id = _CHAIN_IDS.get(chain, 8453)
        contracts = _EVM_TOKEN_CONTRACTS.get(chain, {})
        contract = contracts.get(token_upper)
        if contract:
            # ERC-20: amount in smallest unit (6 decimals for USDC)
            decimals = 6 if token_upper in ("USDC", "USDT") else 18
            amount_wei = int(amount * (10**decimals))
            return (
                f"ethereum:{contract}@{chain_id}/transfer"
                f"?address={address}&uint256={amount_wei}"
            )
        # Native token
        return f"ethereum:{address}@{chain_id}?value={int(amount * 10**18)}"
