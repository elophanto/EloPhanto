"""Stripe fiat rail provider — the fiat half of the ABE finance rail.

Slice 1 (Spine + Hold): read-only `cash_on_hand()` from the Stripe Balance
API, used to compute runway (see core/ledger.runway_weeks). Receive (payment
links) and spend (Issuing) are later slices.

Finance invariants honored here (tmp/abe-finance-rail-spec-2026-06-18.md §0):
- The secret key is read from the vault per call and NEVER logged.
- `mode=test`/`live` must match the key's environment (sk_test_/sk_live_) —
  a live key under test mode (or vice versa) is refused, not silently used.
- The synchronous Stripe SDK is run off the event loop via asyncio.to_thread.
- No global `stripe.api_key` mutation — the key is passed per request, so
  concurrent providers can't clobber each other.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.config import PaymentFiatConfig

logger = logging.getLogger(__name__)


class FiatRailError(Exception):
    """Raised on a fiat-rail misconfiguration or API failure. Messages never
    contain secret material."""


class StripeFiatProvider:
    """Read-only Stripe access for Slice 1: balance → cash-on-hand.

    ``vault`` is a ``core.vault.Vault`` (or any object with ``.get(ref)``);
    kept untyped to avoid an import cycle and to allow a fake in tests.
    """

    def __init__(self, config: PaymentFiatConfig, vault: Any = None) -> None:
        self._config = config
        self._vault = vault

    @property
    def is_test_mode(self) -> bool:
        """True unless mode is explicitly 'live'. Safe default: anything that
        isn't 'live' is treated as test (no real money)."""
        return (self._config.mode or "test").strip().lower() != "live"

    def _secret_key(self) -> str:
        """Fetch the Stripe secret key from the vault and assert it matches
        the configured mode. Never logs the key."""
        raw = self._vault.get(self._config.secret_key_ref) if self._vault else None
        if not raw:
            raise FiatRailError(
                f"Stripe secret key not found in vault under "
                f"{self._config.secret_key_ref!r}. Add it with the wizard or "
                f"`elophanto vault set {self._config.secret_key_ref} <key>`."
            )
        key = str(raw).strip()
        # Mode/key environment must agree — the single most dangerous
        # misconfiguration is a LIVE key running while the operator believes
        # they're in the test sandbox.
        if self.is_test_mode and key.startswith("sk_live_"):
            raise FiatRailError(
                "mode=test but a LIVE Stripe key is configured — refusing "
                "(this would move real money). Use an sk_test_ key, or set "
                "payments.fiat.mode: live deliberately."
            )
        if not self.is_test_mode and key.startswith("sk_test_"):
            raise FiatRailError(
                "mode=live but a TEST Stripe key is configured — this would "
                "not move real money. Use an sk_live_ key."
            )
        return key

    @staticmethod
    def _sum_balance(payload: dict[str, Any], currency: str) -> float:
        """Sum available + pending amounts in ``currency`` from a Stripe
        Balance payload. Stripe amounts are in the currency's minor unit
        (cents); returns major units (dollars). Pure — unit-tested directly."""
        ccy = (currency or "USD").strip().lower()
        cents = 0
        for bucket in ("available", "pending"):
            for entry in payload.get(bucket) or []:
                if str(entry.get("currency", "")).strip().lower() == ccy:
                    cents += int(entry.get("amount") or 0)
        return cents / 100.0

    def _retrieve_balance_sync(self) -> float:
        """Blocking Balance API read. Runs in a worker thread (see
        cash_on_hand). Lazy-imports stripe so the dep stays optional."""
        try:
            import stripe
        except ImportError as e:  # pragma: no cover - depends on extra
            raise FiatRailError(
                "stripe is not installed — run: " "uv pip install -e '.[payments-fiat]'"
            ) from e
        try:
            bal = stripe.Balance.retrieve(api_key=self._secret_key())
        except FiatRailError:
            raise
        except Exception as e:  # Stripe errors, network, auth — normalize
            # Do not interpolate the exception verbatim if it could echo the
            # key; Stripe's errors don't, but be conservative with the type.
            raise FiatRailError(
                f"Stripe balance retrieval failed: {type(e).__name__}"
            ) from e
        payload = bal.to_dict() if hasattr(bal, "to_dict") else dict(bal)
        return self._sum_balance(payload, self._config.base_currency)

    async def cash_on_hand(self) -> float:
        """Spendable-soon balance (available + pending) in base currency.

        NOTE: this is the Stripe balance, NOT the bank balance — Stripe pays
        out to the bank on a settlement lag (§5/§6.7 of the spec). It is the
        right figure for "cash I can deploy soon"; runway is computed off it.
        Runs the blocking SDK call off the event loop.
        """
        return await asyncio.to_thread(self._retrieve_balance_sync)
