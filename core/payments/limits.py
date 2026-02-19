"""Spending limit enforcement for agent payments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.payments.audit import PaymentAuditor

logger = logging.getLogger(__name__)


@dataclass
class SpendingCheck:
    """Result of a spending limit check."""

    allowed: bool
    reason: str = ""
    daily_spent: float = 0.0
    monthly_spent: float = 0.0


class SpendingLimiter:
    """Enforces per-transaction, daily, monthly, and per-merchant spending limits."""

    def __init__(self, auditor: PaymentAuditor, config: Any) -> None:
        self._auditor = auditor
        self._config = config

    async def check(self, amount: float, currency: str, recipient: str) -> SpendingCheck:
        """Check all spending limits. Returns SpendingCheck."""
        # Per-transaction limit
        if amount > self._config.per_transaction:
            return SpendingCheck(
                allowed=False,
                reason=f"Amount ${amount:.2f} exceeds per-transaction limit of "
                f"${self._config.per_transaction:.2f}",
            )

        # Daily rolling 24h limit
        daily_spent = await self._auditor.get_daily_total()
        if daily_spent + amount > self._config.daily:
            return SpendingCheck(
                allowed=False,
                reason=f"Would exceed daily limit: ${daily_spent:.2f} spent + "
                f"${amount:.2f} = ${daily_spent + amount:.2f} > ${self._config.daily:.2f}",
                daily_spent=daily_spent,
            )

        # Monthly calendar limit
        monthly_spent = await self._auditor.get_monthly_total()
        if monthly_spent + amount > self._config.monthly:
            return SpendingCheck(
                allowed=False,
                reason=f"Would exceed monthly limit: ${monthly_spent:.2f} spent + "
                f"${amount:.2f} > ${self._config.monthly:.2f}",
                daily_spent=daily_spent,
                monthly_spent=monthly_spent,
            )

        # Per-recipient daily limit
        recipient_daily = await self._auditor.get_recipient_daily_total(recipient)
        if recipient_daily + amount > self._config.per_merchant_daily:
            return SpendingCheck(
                allowed=False,
                reason=f"Would exceed per-recipient daily limit for {recipient}: "
                f"${recipient_daily:.2f} + ${amount:.2f} > "
                f"${self._config.per_merchant_daily:.2f}",
                daily_spent=daily_spent,
                monthly_spent=monthly_spent,
            )

        # Rate limit: max 10 transactions per hour
        hourly_count = await self._auditor.get_hourly_count()
        if hourly_count >= 10:
            return SpendingCheck(
                allowed=False,
                reason="Rate limit: maximum 10 transactions per hour reached",
                daily_spent=daily_spent,
                monthly_spent=monthly_spent,
            )

        # Duplicate detection: same amount + recipient within 1 hour
        if await self._auditor.has_recent_duplicate(amount, recipient):
            return SpendingCheck(
                allowed=False,
                reason=f"Duplicate detected: ${amount:.2f} to {recipient} "
                f"already sent within the last hour",
                daily_spent=daily_spent,
                monthly_spent=monthly_spent,
            )

        return SpendingCheck(
            allowed=True,
            daily_spent=daily_spent,
            monthly_spent=monthly_spent,
        )

    def get_approval_tier(self, amount: float) -> str:
        """Return approval tier based on amount."""
        approval = self._config
        # Access parent config's approval section — caller passes approval config
        if hasattr(approval, "cooldown_above"):
            if amount >= approval.cooldown_above:
                return "cooldown"
            if amount >= approval.confirm_above:
                return "confirm"
            if amount >= approval.always_ask_above:
                return "always_ask"
        return "standard"
