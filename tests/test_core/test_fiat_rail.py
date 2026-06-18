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


# ── Receive: payment link (Slice 2) ──────────────────────────────────


class _FakeStripe:
    """Minimal stand-in for the stripe SDK — captures call kwargs."""

    def __init__(self) -> None:
        self.captured: dict[str, dict] = {}

    class _Price:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kw):
            self._outer.captured["price"] = kw
            return {"id": "price_1"}

    class _PaymentLink:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kw):
            self._outer.captured["link"] = kw
            return {"id": "plink_1", "url": "https://pay.stripe.com/test_abc"}

    @property
    def Price(self):
        return self._Price(self)

    @property
    def PaymentLink(self):
        return self._PaymentLink(self)


class TestCreatePaymentLink:
    @pytest.mark.asyncio
    async def test_create_link_converts_amount_and_passes_idempotency(
        self, monkeypatch
    ) -> None:
        provider = StripeFiatProvider(
            PaymentFiatConfig(mode="test", base_currency="USD"),
            _FakeVault({"stripe_secret_key": "sk_test_x"}),
        )
        fake = _FakeStripe()
        monkeypatch.setattr(provider, "_import_stripe", lambda: fake)
        res = await provider.create_payment_link(
            amount=49.0, description="2026 SE Guide", idempotency_key="abc"
        )
        assert res["id"] == "plink_1"
        assert res["url"].startswith("https://pay.stripe.com/")
        assert res["amount"] == 49.0
        assert res["mode"] == "test"
        # $49.00 → 4900 cents
        assert fake.captured["price"]["unit_amount"] == 4900
        # idempotency keys make SDK retries safe
        assert fake.captured["price"]["idempotency_key"] == "abc:price"
        assert fake.captured["link"]["idempotency_key"] == "abc:link"

    @pytest.mark.asyncio
    async def test_create_link_rejects_nonpositive(self) -> None:
        provider = StripeFiatProvider(
            PaymentFiatConfig(mode="test"),
            _FakeVault({"stripe_secret_key": "sk_test_x"}),
        )
        with pytest.raises(FiatRailError, match="positive"):
            await provider.create_payment_link(
                amount=0, description="x", idempotency_key="k"
            )


def _link_tool(mode: str = "test", enabled: bool = True, company_manager=None):
    from types import SimpleNamespace

    from tools.payments.fiat_link_tool import FiatPaymentLinkTool

    fiat = PaymentFiatConfig(enabled=enabled, mode=mode)
    t = FiatPaymentLinkTool()
    t._config = SimpleNamespace(payments=SimpleNamespace(fiat=fiat))
    t._vault = _FakeVault({"stripe_secret_key": "sk_test_x"})
    t._company_manager = company_manager
    return t


class TestFiatLinkTool:
    @pytest.mark.asyncio
    async def test_disabled(self) -> None:
        r = await _link_tool(enabled=False).execute({"amount": 49, "description": "x"})
        assert r.success is False
        assert "not enabled" in (r.error or "")

    @pytest.mark.asyncio
    async def test_live_unverified_blocked(self) -> None:
        class CM:
            async def get_entity_state(self, cid):
                return "kyc_pending"

        r = await _link_tool(mode="live", company_manager=CM()).execute(
            {"amount": 49, "description": "x"}
        )
        assert r.success is False
        assert "verified" in (r.error or "")

    @pytest.mark.asyncio
    async def test_invalid_amount(self) -> None:
        r = await _link_tool().execute({"amount": 0, "description": "x"})
        assert r.success is False

    @pytest.mark.asyncio
    async def test_missing_description(self) -> None:
        r = await _link_tool().execute({"amount": 49, "description": "  "})
        assert r.success is False

    @pytest.mark.asyncio
    async def test_test_mode_success(self, monkeypatch) -> None:
        async def _fake_create(
            self, *, amount, description, currency=None, idempotency_key
        ):
            return {
                "id": "plink_1",
                "url": "https://pay.stripe.com/test_abc",
                "amount": amount,
                "currency": "usd",
                "mode": "test",
            }

        monkeypatch.setattr(StripeFiatProvider, "create_payment_link", _fake_create)
        r = await _link_tool(mode="test").execute(
            {"amount": 49, "description": "2026 Guide"}
        )
        assert r.success is True
        assert r.data["url"].startswith("https://pay.stripe.com/")
        assert "TEST" in r.data["note"]


# ── Slice 2b: mode-aware ledger + reconcile ──────────────────────────


class TestModeAwareLedger:
    @pytest.mark.asyncio
    async def test_test_receipts_excluded_from_live_metabolism(self, db) -> None:
        # §6.8: test-mode receipts must NOT count as real revenue.
        ledger = ResourceLedger(db)
        await ledger.write(LedgerEntry("acme", "in", "usd", 100.0, "usd", mode="live"))
        await ledger.write(LedgerEntry("acme", "in", "usd", 999.0, "usd", mode="test"))
        live = await ledger.metabolism("acme")  # default mode='live'
        assert live.revenue_usd == 100.0
        test = await ledger.metabolism("acme", mode="test")
        assert test.revenue_usd == 999.0
        both = await ledger.sum("acme", type="usd", direction="in", mode=None)
        assert both == 1099.0

    @pytest.mark.asyncio
    async def test_write_defaults_to_live(self, db) -> None:
        ledger = ResourceLedger(db)
        await ledger.write(LedgerEntry("acme", "in", "usd", 50.0, "usd"))
        assert await ledger.sum("acme", type="usd", direction="in") == 50.0

    @pytest.mark.asyncio
    async def test_note_exists_dedupe(self, db) -> None:
        ledger = ResourceLedger(db)
        assert await ledger.note_exists("acme", "stripe:pi_1") is False
        await ledger.write(
            LedgerEntry("acme", "in", "usd", 10.0, "usd", note="stripe:pi_1")
        )
        assert await ledger.note_exists("acme", "stripe:pi_1") is True


class _FakeStripeList:
    def __init__(self, payments: list[dict]) -> None:
        self._payments = payments

    @property
    def PaymentIntent(self):
        payments = self._payments

        class _PI:
            @staticmethod
            def list(**kw):
                return {"data": payments}

        return _PI


class TestListRecentPayments:
    @pytest.mark.asyncio
    async def test_filters_succeeded_and_converts(self, monkeypatch) -> None:
        provider = StripeFiatProvider(
            PaymentFiatConfig(mode="test"),
            _FakeVault({"stripe_secret_key": "sk_test_x"}),
        )
        fake = _FakeStripeList(
            [
                {
                    "id": "pi_1",
                    "status": "succeeded",
                    "amount": 4900,
                    "currency": "usd",
                },
                {
                    "id": "pi_2",
                    "status": "requires_payment_method",
                    "amount": 100,
                    "currency": "usd",
                },
            ]
        )
        monkeypatch.setattr(provider, "_import_stripe", lambda: fake)
        out = await provider.list_recent_payments()
        assert len(out) == 1
        assert out[0]["id"] == "pi_1"
        assert out[0]["amount"] == 49.0


def _reconcile_tool(db, mode: str = "test", enabled: bool = True):
    from types import SimpleNamespace

    from tools.payments.fiat_reconcile_tool import FiatReconcileTool

    fiat = PaymentFiatConfig(enabled=enabled, mode=mode)
    t = FiatReconcileTool()
    t._config = SimpleNamespace(payments=SimpleNamespace(fiat=fiat))
    t._vault = _FakeVault({"stripe_secret_key": "sk_test_x"})
    t._db = db
    t._company_manager = None
    return t


async def _no_refunds(self, *, limit=100):
    return []


class TestFiatReconcile:
    @pytest.mark.asyncio
    async def test_disabled(self, db) -> None:
        r = await _reconcile_tool(db, enabled=False).execute({})
        assert r.success is False

    @pytest.mark.asyncio
    async def test_mirrors_then_dedupes_and_excludes_test_from_live(
        self, db, monkeypatch
    ) -> None:
        from core.company import current_company_id

        payments = [
            {"id": "pi_1", "amount": 49.0, "currency": "usd"},
            {"id": "pi_2", "amount": 79.0, "currency": "usd"},
        ]

        async def fake_list(self, *, limit=100):
            return payments

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_list)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", _no_refunds)
        tool = _reconcile_tool(db, mode="test")

        r1 = await tool.execute({})
        assert r1.success is True
        assert r1.data["mirrored"] == 2
        assert r1.data["total_recorded_usd"] == 128.0
        assert r1.data["mode"] == "test"

        # Idempotent — re-run records nothing new.
        r2 = await tool.execute({})
        assert r2.data["mirrored"] == 0
        assert r2.data["already_recorded"] == 2

        # §6.8: recorded as test → excluded from live revenue.
        ledger = ResourceLedger(db)
        cid = current_company_id()
        assert await ledger.sum(cid, type="usd", direction="in") == 0.0  # live
        assert await ledger.sum(cid, type="usd", direction="in", mode="test") == 128.0

    @pytest.mark.asyncio
    async def test_live_mode_records_real_revenue(self, db, monkeypatch) -> None:
        # The "first unattended dollar" path: live reconcile → live revenue.
        from core.company import current_company_id

        async def fake_list(self, *, limit=100):
            return [{"id": "pi_x", "amount": 49.0, "currency": "usd"}]

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_list)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", _no_refunds)
        r = await _reconcile_tool(db, mode="live").execute({})
        assert r.data["mirrored"] == 1
        ledger = ResourceLedger(db)
        # Counts as real (live) revenue → shows in metabolism.
        assert (
            await ledger.sum(current_company_id(), type="usd", direction="in") == 49.0
        )

    @pytest.mark.asyncio
    async def test_refund_reverses_revenue(self, db, monkeypatch) -> None:
        # §6.5: a refund records a compensating usd-OUT → net drops by it.
        from core.company import current_company_id

        async def fake_pay(self, *, limit=100):
            return [{"id": "pi_1", "amount": 49.0, "currency": "usd"}]

        async def fake_ref(self, *, limit=100):
            return [
                {
                    "id": "re_1",
                    "amount": 49.0,
                    "currency": "usd",
                    "payment_intent": "pi_1",
                }
            ]

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_pay)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", fake_ref)
        r = await _reconcile_tool(db, mode="live").execute({})
        assert r.data["mirrored"] == 1
        assert r.data["refunds_recorded"] == 1
        assert r.data["net_recorded_usd"] == 0.0
        # net = revenue_in(49) - spend_out(49) = 0
        met = await ResourceLedger(db).metabolism(current_company_id())
        assert met.revenue_usd == 49.0
        assert met.spend_usd == 49.0
        assert met.net_usd == 0.0

    @pytest.mark.asyncio
    async def test_refund_idempotent(self, db, monkeypatch) -> None:
        async def fake_pay(self, *, limit=100):
            return []

        async def fake_ref(self, *, limit=100):
            return [
                {
                    "id": "re_1",
                    "amount": 10.0,
                    "currency": "usd",
                    "payment_intent": "pi_1",
                }
            ]

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_pay)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", fake_ref)
        tool = _reconcile_tool(db, mode="live")
        r1 = await tool.execute({})
        assert r1.data["refunds_recorded"] == 1
        r2 = await tool.execute({})
        assert r2.data["refunds_recorded"] == 0

    @pytest.mark.asyncio
    async def test_refund_list_failure_is_best_effort(self, db, monkeypatch) -> None:
        # A refund-list failure must NOT undo the payment recording; it just
        # flags refunds_checked=False so net isn't silently overstated.
        async def fake_pay(self, *, limit=100):
            return [{"id": "pi_1", "amount": 49.0, "currency": "usd"}]

        async def fake_ref_fail(self, *, limit=100):
            raise RuntimeError("stripe down")

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_pay)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", fake_ref_fail)
        r = await _reconcile_tool(db, mode="live").execute({})
        assert r.success is True
        assert r.data["mirrored"] == 1
        assert r.data["refunds_checked"] is False

    @pytest.mark.asyncio
    async def test_explicit_company_id_routing(self, db, monkeypatch) -> None:
        # A scheduled reconcile passes company_id explicitly so it records
        # under the right business regardless of fire-time context.
        from core.company import current_company_id

        async def fake_pay(self, *, limit=100):
            return [{"id": "pi_z", "amount": 20.0, "currency": "usd"}]

        monkeypatch.setattr(StripeFiatProvider, "list_recent_payments", fake_pay)
        monkeypatch.setattr(StripeFiatProvider, "list_recent_refunds", _no_refunds)
        r = await _reconcile_tool(db, mode="live").execute({"company_id": "acme-co"})
        assert r.data["mirrored"] == 1
        ledger = ResourceLedger(db)
        # Recorded under acme-co, NOT the default/active company.
        assert await ledger.sum("acme-co", type="usd", direction="in") == 20.0
        assert await ledger.sum(current_company_id(), type="usd", direction="in") == 0.0


class _FakeScheduler:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self._existing: list = []

    async def list_schedules(self):
        return list(self._existing)

    async def create_schedule(self, **kw):
        from types import SimpleNamespace

        e = SimpleNamespace(name=kw["name"], direct_tool=kw.get("direct_tool"))
        self.created.append(kw)
        self._existing.append(e)
        return e


class _FakeCM:
    def __init__(self, companies) -> None:
        self._c = companies

    async def list(self):
        return self._c


def _agent_for_seed(scheduler, company_manager, fiat_enabled=True):
    from types import SimpleNamespace

    from core.agent import Agent

    a = Agent.__new__(Agent)
    a._scheduler = scheduler
    a._company_manager = company_manager
    a._config = SimpleNamespace(
        payments=SimpleNamespace(fiat=PaymentFiatConfig(enabled=fiat_enabled))
    )
    return a


class TestFiatReconcileSeed:
    @pytest.mark.asyncio
    async def test_seeds_only_active_fiat_companies(self) -> None:
        from types import SimpleNamespace

        companies = [
            SimpleNamespace(id="acme", status="active", payment_rail="fiat"),
            SimpleNamespace(id="selfco", status="active", payment_rail=None),
            SimpleNamespace(id="cryptoco", status="active", payment_rail="crypto"),
            SimpleNamespace(id="old", status="archived", payment_rail="fiat"),
        ]
        sched = _FakeScheduler()
        agent = _agent_for_seed(sched, _FakeCM(companies))
        await agent._seed_fiat_reconcile_schedules()
        # Only the active fiat company gets a reconcile schedule.
        assert [c["name"] for c in sched.created] == ["fiat-reconcile-acme"]
        assert sched.created[0]["direct_tool"] == "fiat_reconcile"
        assert sched.created[0]["direct_params"] == {"company_id": "acme"}
        # Idempotent — second run creates nothing new.
        await agent._seed_fiat_reconcile_schedules()
        assert len(sched.created) == 1

    @pytest.mark.asyncio
    async def test_seed_skips_when_fiat_disabled(self) -> None:
        from types import SimpleNamespace

        sched = _FakeScheduler()
        companies = [SimpleNamespace(id="acme", status="active", payment_rail="fiat")]
        agent = _agent_for_seed(sched, _FakeCM(companies), fiat_enabled=False)
        await agent._seed_fiat_reconcile_schedules()
        assert sched.created == []

    @pytest.mark.asyncio
    async def test_seed_no_scheduler_is_safe(self) -> None:
        agent = _agent_for_seed(None, None)
        await agent._seed_fiat_reconcile_schedules()  # must not raise
