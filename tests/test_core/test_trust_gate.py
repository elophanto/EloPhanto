"""Trust gate + trust ladder (ABE Phase 9).

Locks in the Phase 9 contract from docs/76-ABE-FRAMEWORK.md:
- New companies default to 'learning' (live outreach refused)
- elophanto-self is bumped to 'operating' on init (the seed exception)
- trial / operating let live outreach through
- Unknown / missing company fails SAFE (denies)
- ValueError on invalid state
- set_trust_state is idempotent
"""

from __future__ import annotations

import pytest

from core.company import (
    VALID_TRUST_STATES,
    CompanyManager,
    set_current_company,
)
from core.database import Database
from core.trust_gate import check_outreach_allowed


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def company_mgr(db: Database, tmp_path) -> CompanyManager:
    return CompanyManager(db=db, project_root=tmp_path)


class TestSeedExemption:
    @pytest.mark.asyncio
    async def test_elophanto_self_is_operating_after_init(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        c = await company_mgr.get("elophanto-self")
        assert c is not None
        assert c.trust_state == "operating", (
            "Seed company must be promoted to 'operating' on init so "
            "existing production schedules keep working — without this, "
            "every existing operator's email_send / twitter_post would "
            "start refusing after the migration."
        )


class TestNewCompanyDefaults:
    @pytest.mark.asyncio
    async def test_new_company_defaults_to_learning(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        c = await company_mgr.create("acme-inc", "Acme")
        assert c.trust_state == "learning"


class TestGateBehavior:
    @pytest.mark.asyncio
    async def test_learning_state_denies_all_outreach(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        set_current_company("test-co")
        for tool in (
            "email_send",
            "email_reply",
            "prospect_outreach",
            "twitter_post",
        ):
            allowed, reason = await check_outreach_allowed(db, tool)
            assert allowed is False, f"learning state must deny {tool}"
            assert "learning" in reason
            # Reason must point at the draft alternative
            assert "draft" in reason.lower()
        set_current_company("elophanto-self")

    @pytest.mark.asyncio
    async def test_trial_state_allows_outreach(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        await company_mgr.set_trust_state("test-co", "trial")
        allowed, _ = await check_outreach_allowed(db, "email_send", "test-co")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_operating_state_allows_outreach(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        allowed, _ = await check_outreach_allowed(db, "email_send", "elophanto-self")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_missing_company_fails_safe(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        # Looking up a non-existent company → trust_state defaults to
        # 'learning' which → deny. The fail-safe is critical: a typo
        # in the contextvar must NEVER unleash live outreach.
        allowed, reason = await check_outreach_allowed(db, "email_send", "no-such-co")
        assert allowed is False
        # Either the regular learning message OR the fail-safe message
        assert "learning" in reason.lower() or "fail-safe" in reason.lower()

    @pytest.mark.asyncio
    async def test_reason_names_replacement_tool(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        replacements = {
            "email_send": "email_draft",
            "email_reply": "email_draft",
            "prospect_outreach": "outreach_draft",
            "twitter_post": "post_draft",
        }
        for tool, replacement in replacements.items():
            allowed, reason = await check_outreach_allowed(db, tool, "test-co")
            assert not allowed
            assert replacement in reason, (
                f"deny reason for {tool} must point operator/agent at "
                f"{replacement} — got: {reason}"
            )


class TestSetTrustState:
    @pytest.mark.asyncio
    async def test_set_trust_state_round_trip(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        assert (await company_mgr.get_trust_state("test-co")) == "learning"
        await company_mgr.set_trust_state("test-co", "trial")
        assert (await company_mgr.get_trust_state("test-co")) == "trial"
        await company_mgr.set_trust_state("test-co", "operating")
        assert (await company_mgr.get_trust_state("test-co")) == "operating"

    @pytest.mark.asyncio
    async def test_set_trust_state_rejects_invalid(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        with pytest.raises(ValueError):
            await company_mgr.set_trust_state("test-co", "bogus")

    @pytest.mark.asyncio
    async def test_set_trust_state_unknown_slug(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        ok = await company_mgr.set_trust_state("no-such-co", "trial")
        assert ok is False

    @pytest.mark.asyncio
    async def test_set_trust_state_idempotent(
        self, db: Database, company_mgr: CompanyManager
    ) -> None:
        await company_mgr.create("test-co", "Test")
        await company_mgr.set_trust_state("test-co", "trial")
        await company_mgr.set_trust_state("test-co", "trial")
        assert (await company_mgr.get_trust_state("test-co")) == "trial"


class TestValidTrustStates:
    def test_valid_states_constant_matches_enum(self) -> None:
        assert VALID_TRUST_STATES == ("learning", "trial", "operating")
