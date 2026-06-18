"""ABE fiat rail — Slice 1 (Spine + Hold).

Covers the Stripe provider's pure/guard logic (no network), the runway math,
and the company finance-state model (payment_rail + entity_state).
See tmp/abe-finance-rail-spec-2026-06-18.md.
"""

from __future__ import annotations

import pytest

from core.company import (
    VALID_ENTITY_STATES,
    VALID_PAYMENT_RAILS,
    CompanyManager,
)
from core.config import PaymentFiatConfig
from core.database import Database
from core.ledger import LedgerEntry, ResourceLedger, runway_weeks
from core.payments.fiat_stripe import FiatRailError, StripeFiatProvider


class _FakeVault:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self._store = store or {}

    def get(self, key: str):
        return self._store.get(key)


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


# ── Stripe provider: pure + guards (no network) ──────────────────────


class TestStripeProvider:
    def test_sum_balance_available_plus_pending(self) -> None:
        payload = {
            "available": [{"amount": 21400, "currency": "usd"}],
            "pending": [{"amount": 600, "currency": "usd"}],
        }
        assert StripeFiatProvider._sum_balance(payload, "USD") == 220.0

    def test_sum_balance_filters_currency(self) -> None:
        payload = {
            "available": [
                {"amount": 10000, "currency": "usd"},
                {"amount": 99999, "currency": "eur"},
            ],
            "pending": [],
        }
        assert StripeFiatProvider._sum_balance(payload, "USD") == 100.0

    def test_sum_balance_empty(self) -> None:
        assert StripeFiatProvider._sum_balance({}, "USD") == 0.0

    def test_is_test_mode_default(self) -> None:
        p = StripeFiatProvider(PaymentFiatConfig(), _FakeVault())
        assert p.is_test_mode is True  # default mode='test'

    def test_is_test_mode_live(self) -> None:
        p = StripeFiatProvider(PaymentFiatConfig(mode="live"), _FakeVault())
        assert p.is_test_mode is False

    def test_secret_key_missing_raises(self) -> None:
        p = StripeFiatProvider(PaymentFiatConfig(), _FakeVault({}))
        with pytest.raises(FiatRailError, match="not found in vault"):
            p._secret_key()

    def test_live_key_in_test_mode_refused(self) -> None:
        # The critical footgun: a LIVE key while the operator thinks they're
        # in the sandbox. Must refuse, not silently move real money.
        p = StripeFiatProvider(
            PaymentFiatConfig(mode="test"),
            _FakeVault({"stripe_secret_key": "sk_live_abc123"}),
        )
        with pytest.raises(FiatRailError, match="LIVE Stripe key"):
            p._secret_key()

    def test_test_key_in_live_mode_refused(self) -> None:
        p = StripeFiatProvider(
            PaymentFiatConfig(mode="live"),
            _FakeVault({"stripe_secret_key": "sk_test_abc123"}),
        )
        with pytest.raises(FiatRailError, match="TEST Stripe key"):
            p._secret_key()

    def test_matching_test_key_ok(self) -> None:
        p = StripeFiatProvider(
            PaymentFiatConfig(mode="test"),
            _FakeVault({"stripe_secret_key": "sk_test_ok"}),
        )
        assert p._secret_key() == "sk_test_ok"

    @pytest.mark.asyncio
    async def test_cash_on_hand_runs_via_thread(self, monkeypatch) -> None:
        p = StripeFiatProvider(PaymentFiatConfig(), _FakeVault())
        monkeypatch.setattr(p, "_retrieve_balance_sync", lambda: 142.5)
        assert await p.cash_on_hand() == 142.5


# ── Runway math ──────────────────────────────────────────────────────


class TestRunwayMath:
    def test_runway_burning(self) -> None:
        assert runway_weeks(cash_on_hand=2000.0, weekly_burn=50.0) == 40.0

    def test_runway_net_positive_is_none(self) -> None:
        assert runway_weeks(cash_on_hand=2000.0, weekly_burn=0.0) is None
        assert runway_weeks(cash_on_hand=2000.0, weekly_burn=-5.0) is None

    def test_runway_out_of_money_is_zero(self) -> None:
        assert runway_weeks(cash_on_hand=0.0, weekly_burn=50.0) == 0.0
        assert runway_weeks(cash_on_hand=-10.0, weekly_burn=50.0) == 0.0

    @pytest.mark.asyncio
    async def test_trailing_weekly_burn(self, db: Database) -> None:
        ledger = ResourceLedger(db)
        # net over window = 20 - 100 = -80 → burn 80/4wk = 20/wk
        await ledger.write(
            LedgerEntry(
                company_id="acme",
                direction="in",
                type="usd",
                amount=20.0,
                unit="usd",
            )
        )
        await ledger.write(
            LedgerEntry(
                company_id="acme",
                direction="out",
                type="usd",
                amount=100.0,
                unit="usd",
            )
        )
        burn = await ledger.trailing_weekly_burn("acme", weeks=4)
        assert burn == 20.0

    @pytest.mark.asyncio
    async def test_trailing_weekly_burn_net_positive_zero(self, db: Database) -> None:
        ledger = ResourceLedger(db)
        await ledger.write(
            LedgerEntry(
                company_id="acme",
                direction="in",
                type="usd",
                amount=500.0,
                unit="usd",
            )
        )
        assert await ledger.trailing_weekly_burn("acme") == 0.0


# ── Company finance state ────────────────────────────────────────────


class TestCompanyFinanceState:
    @pytest.mark.asyncio
    async def test_defaults(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        c = await cm.get("acme")
        assert c is not None
        assert c.payment_rail is None  # unchosen until onboard
        assert c.entity_state == "none"

    @pytest.mark.asyncio
    async def test_set_payment_rail(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        assert await cm.set_payment_rail("acme", "fiat") is True
        assert (await cm.get("acme")).payment_rail == "fiat"

    @pytest.mark.asyncio
    async def test_set_payment_rail_invalid(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        with pytest.raises(ValueError, match="invalid payment_rail"):
            await cm.set_payment_rail("acme", "paypal")

    @pytest.mark.asyncio
    async def test_set_payment_rail_unknown_company(self, db: Database) -> None:
        cm = CompanyManager(db)
        assert await cm.set_payment_rail("ghost", "fiat") is False

    @pytest.mark.asyncio
    async def test_entity_state_lifecycle(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        for state in ("forming", "kyc_pending", "verified", "restricted"):
            assert await cm.set_entity_state("acme", state) is True
            assert await cm.get_entity_state("acme") == state

    @pytest.mark.asyncio
    async def test_entity_state_invalid(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        with pytest.raises(ValueError, match="invalid entity_state"):
            await cm.set_entity_state("acme", "live")  # not a valid state

    @pytest.mark.asyncio
    async def test_get_entity_state_unknown_company_failsafe(
        self, db: Database
    ) -> None:
        cm = CompanyManager(db)
        # Fail safe: unknown company → 'none' (money gate denies).
        assert await cm.get_entity_state("ghost") == "none"

    @pytest.mark.asyncio
    async def test_rail_and_entity_round_trip_via_list(self, db: Database) -> None:
        cm = CompanyManager(db)
        await cm.create("acme", "Acme")
        await cm.set_payment_rail("acme", "crypto")
        await cm.set_entity_state("acme", "verified")
        listed = {c.id: c for c in await cm.list()}
        assert listed["acme"].payment_rail == "crypto"
        assert listed["acme"].entity_state == "verified"

    def test_valid_sets(self) -> None:
        assert VALID_PAYMENT_RAILS == ("fiat", "crypto")
        assert "verified" in VALID_ENTITY_STATES and "none" in VALID_ENTITY_STATES


# ── State-line finance marker (rendering branches, no network) ────────


def _mind_with_fiat(mode: str = "test", enabled: bool = True):
    from types import SimpleNamespace

    from core.autonomous_mind import AutonomousMind

    fiat = PaymentFiatConfig(enabled=enabled, mode=mode)
    agent = SimpleNamespace(
        _config=SimpleNamespace(payments=SimpleNamespace(fiat=fiat)),
        _vault=None,
        _db=None,
    )
    mind = AutonomousMind.__new__(AutonomousMind)
    mind._agent = agent
    return mind


def _company(rail=None, entity="none"):
    from types import SimpleNamespace

    return SimpleNamespace(id="acme", payment_rail=rail, entity_state=entity)


class TestFinanceMarker:
    @pytest.mark.asyncio
    async def test_no_rail_blank(self) -> None:
        m = _mind_with_fiat()
        assert await m._finance_marker(_company(rail=None)) == ""

    @pytest.mark.asyncio
    async def test_crypto_rail(self) -> None:
        m = _mind_with_fiat()
        assert await m._finance_marker(_company(rail="crypto")) == " rail=crypto"

    @pytest.mark.asyncio
    async def test_fiat_disabled(self) -> None:
        m = _mind_with_fiat(enabled=False)
        assert await m._finance_marker(_company(rail="fiat")) == " rail=fiat(off)"

    @pytest.mark.asyncio
    async def test_fiat_test_mode_no_cash_or_runway(self) -> None:
        # §6.8: test-mode balance is fake — must NOT surface cash/runway.
        m = _mind_with_fiat(mode="test")
        marker = await m._finance_marker(_company(rail="fiat", entity="verified"))
        assert marker == " rail=fiat[mode=TEST]"
        assert "cash" not in marker and "runway" not in marker

    @pytest.mark.asyncio
    async def test_fiat_live_unverified_no_money(self) -> None:
        # Live mode but KYC not done → no cash read, just the gated marker.
        m = _mind_with_fiat(mode="live")
        marker = await m._finance_marker(_company(rail="fiat", entity="kyc_pending"))
        assert marker == " rail=fiat[LIVE,entity=kyc_pending]"
        assert "cash" not in marker

    @pytest.mark.asyncio
    async def test_finance_marker_never_raises(self) -> None:
        # Broken agent config must degrade to a safe string, not crash the
        # whole state-snapshot build.
        from types import SimpleNamespace

        from core.autonomous_mind import AutonomousMind

        mind = AutonomousMind.__new__(AutonomousMind)
        mind._agent = SimpleNamespace()  # no _config at all
        assert await mind._finance_marker(_company(rail="fiat")) == " rail=fiat"


class TestDoctorFiatCheck:
    def _cfg(self, tmp_path, body: str):
        p = tmp_path / "config.yaml"
        p.write_text(body, encoding="utf-8")
        return tmp_path

    def test_disabled_skips(self, tmp_path) -> None:
        from cli.doctor_cmd import _check_fiat

        r = _check_fiat(self._cfg(tmp_path, "payments:\n  enabled: true\n"))
        assert r.status == "skip"

    def test_test_mode_ok(self, tmp_path) -> None:
        from cli.doctor_cmd import _check_fiat

        r = _check_fiat(
            self._cfg(
                tmp_path, "payments:\n  fiat:\n    enabled: true\n    mode: test\n"
            )
        )
        assert r.status == "ok"
        assert "TEST" in r.detail

    def test_live_mode_warns(self, tmp_path) -> None:
        from cli.doctor_cmd import _check_fiat

        r = _check_fiat(
            self._cfg(
                tmp_path, "payments:\n  fiat:\n    enabled: true\n    mode: live\n"
            )
        )
        assert r.status == "warn"
        assert "LIVE" in r.detail
