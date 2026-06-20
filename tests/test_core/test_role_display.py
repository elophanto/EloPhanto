"""Reality-based role display identity (ABE role visibility, docs/76 §Phase 2).

Locks in the contract that makes the org legible to the operator:
- title tier is driven by REAL money (Metabolism), never inflated
- resolve_role_display degrades DOWN a partial ladder, never up
- role YAMLs round-trip emoji + titles through the DB
- every production role ships a complete display identity
- the <org_roles> prompt block is reality-based + anti-theater
- response_message carries the role badge fields
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.database import Database
from core.ledger import LedgerEntry, Metabolism, ResourceLedger
from core.protocol import response_message
from core.role import Role, RoleManager
from core.role_display import (
    TIER_CHIEF,
    TIER_IC,
    TIER_LEAD,
    badge_text,
    build_role_roster_context,
    display_for_company_role,
    display_for_current,
    resolve_role_display,
    seniority_tier,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROLES_DIR = _REPO_ROOT / "roles"


def _met(revenue: float, spend: float) -> Metabolism:
    return Metabolism(revenue_usd=revenue, spend_usd=spend, cognition_usd=0.0)


def _role(name: str, emoji: str, titles: dict[str, str], desc: str = "") -> Role:
    return Role(name=name, description=desc, emoji=emoji, titles=titles)


_MARKETING = _role(
    "marketing", "📣", {"ic": "Marketing", "lead": "Head of Marketing", "chief": "CMO"}
)
_CEO = _role("ceo", "👔", {"ic": "Founder", "lead": "CEO", "chief": "CEO"})


# ── seniority_tier — driven by real money ──────────────────────────────


class TestSeniorityTier:
    def test_no_metabolism_is_ic(self) -> None:
        assert seniority_tier(None) == TIER_IC

    def test_no_revenue_is_ic(self) -> None:
        # Pre-traction: the founder wears every hat.
        assert seniority_tier(_met(0, 5)) == TIER_IC

    def test_revenue_but_burning_is_lead(self) -> None:
        # Real money flowing but still subsidized — a function to "head".
        assert seniority_tier(_met(10, 50)) == TIER_LEAD

    def test_net_positive_is_chief(self) -> None:
        # Self-sustaining — chief titles are earned.
        assert seniority_tier(_met(100, 40)) == TIER_CHIEF

    def test_break_even_is_lead_not_chief(self) -> None:
        # net == 0 is not yet self-sustaining.
        assert seniority_tier(_met(40, 40)) == TIER_LEAD


# ── resolve_role_display — reality-based, never inflates ───────────────


class TestResolveRoleDisplay:
    def test_pre_revenue_marketing_is_ic(self) -> None:
        assert resolve_role_display(_MARKETING, None) == ("📣", "Marketing")

    def test_revenue_marketing_is_head(self) -> None:
        assert resolve_role_display(_MARKETING, _met(10, 50)) == (
            "📣",
            "Head of Marketing",
        )

    def test_profitable_marketing_is_cmo(self) -> None:
        assert resolve_role_display(_MARKETING, _met(100, 40)) == ("📣", "CMO")

    def test_pre_revenue_ceo_is_founder(self) -> None:
        # The whole point: a pre-revenue CEO is a Founder, not a "CEO".
        assert resolve_role_display(_CEO, None) == ("👔", "Founder")

    def test_partial_ladder_degrades_down_never_up(self) -> None:
        # Only ic is filled; even at chief-tier economics it must NOT inflate.
        only_ic = _role("x", "🧪", {"ic": "Specialist"})
        assert resolve_role_display(only_ic, _met(100, 40)) == ("🧪", "Specialist")

    def test_missing_lead_falls_back_to_ic(self) -> None:
        gap = _role("x", "🧪", {"ic": "Junior", "chief": "Chief"})
        # lead-tier economics, lead missing → fall DOWN to ic, not up to chief.
        assert resolve_role_display(gap, _met(10, 50)) == ("🧪", "Junior")

    def test_empty_titles_uses_name_fallback(self) -> None:
        bare = _role("growth_hacker", "🧪", {})
        assert resolve_role_display(bare, _met(100, 40)) == ("🧪", "Growth Hacker")

    def test_none_role_is_neutral_default(self) -> None:
        assert resolve_role_display(None, None) == ("👔", "Founder")


# ── badge_text ─────────────────────────────────────────────────────────


def test_badge_text() -> None:
    assert badge_text("📣", "Head of Marketing") == "📣 Head of Marketing"
    assert badge_text("", "") == ""
    assert badge_text("📣", "") == ""


# ── production role files all ship a complete display identity ─────────


class TestProductionRoles:
    def test_every_role_has_emoji_and_full_ladder(self) -> None:
        files = sorted(_ROLES_DIR.glob("*.yaml"))
        assert files, "no role YAMLs found"
        for path in files:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert data.get("emoji"), f"{path.name}: missing emoji"
            titles = data.get("titles") or {}
            for tier in ("ic", "lead", "chief"):
                assert titles.get(tier), f"{path.name}: missing titles.{tier}"

    def test_ceo_is_founder_at_ic(self) -> None:
        data = yaml.safe_load((_ROLES_DIR / "ceo.yaml").read_text())
        assert data["titles"]["ic"] == "Founder"


# ── DB round-trip: emoji + titles survive sync ─────────────────────────


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.initialize()
    return d


class TestRoleRoundTrip:
    @pytest.mark.asyncio
    async def test_yaml_emoji_titles_roundtrip(self, db: Database, tmp_path) -> None:
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        (roles_dir / "marketing.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "marketing",
                    "description": "Public presence",
                    "emoji": "📣",
                    "titles": {
                        "ic": "Marketing",
                        "lead": "Head of Marketing",
                        "chief": "CMO",
                    },
                }
            ),
            encoding="utf-8",
        )
        mgr = RoleManager(db=db, roles_dir=roles_dir)
        assert await mgr.sync_from_disk() == 1

        role = await mgr.get("marketing")
        assert role is not None
        assert role.emoji == "📣"
        assert role.titles == {
            "ic": "Marketing",
            "lead": "Head of Marketing",
            "chief": "CMO",
        }
        # And it resolves reality-based off the persisted ladder.
        assert resolve_role_display(role, None) == ("📣", "Marketing")

    @pytest.mark.asyncio
    async def test_display_for_company_role_end_to_end(
        self, db: Database, tmp_path
    ) -> None:
        roles_dir = tmp_path / "roles"
        roles_dir.mkdir()
        (roles_dir / "ceo.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "ceo",
                    "emoji": "👔",
                    "titles": {"ic": "Founder", "lead": "CEO", "chief": "CEO"},
                }
            ),
            encoding="utf-8",
        )
        mgr = RoleManager(db=db, roles_dir=roles_dir)
        await mgr.sync_from_disk()
        ledger = ResourceLedger(db)

        # No money yet → Founder.
        emoji, title = await display_for_company_role(
            role_manager=mgr, ledger=ledger, company_id="c1", role_name="ceo"
        )
        assert (emoji, title) == ("👔", "Founder")

        # Self-sustaining → CEO.
        await ledger.write(
            LedgerEntry(
                company_id="c1", direction="in", type="usd", amount=500.0, unit="usd"
            )
        )
        await ledger.write(
            LedgerEntry(
                company_id="c1", direction="out", type="usd", amount=100.0, unit="usd"
            )
        )
        emoji, title = await display_for_company_role(
            role_manager=mgr, ledger=ledger, company_id="c1", role_name="ceo"
        )
        assert (emoji, title) == ("👔", "CEO")

    @pytest.mark.asyncio
    async def test_display_for_current_no_manager_defaults(self) -> None:
        assert await display_for_current(None, None) == ("👔", "Founder")


# ── <org_roles> roster block ───────────────────────────────────────────


class _FakeRM:
    def __init__(self, roles: list[Role]) -> None:
        self._roles = roles

    async def list_roles(self) -> list[Role]:
        return list(self._roles)


class TestRosterContext:
    @pytest.mark.asyncio
    async def test_roster_is_reality_based_and_anti_theater(self) -> None:
        rm = _FakeRM([_MARKETING, _CEO])
        ctx = await build_role_roster_context(
            role_manager=rm, ledger=None, company_id=None
        )
        assert "<org_roles>" in ctx and "</org_roles>" in ctx
        # Pre-revenue → IC titles, never inflated.
        assert "Founder" in ctx and "📣 Marketing" in ctx
        assert "CMO" not in ctx and "Head of Marketing" not in ctx.split("e.g.")[0]
        # The attribution doctrine + anti-theater guardrail are present.
        assert "ATTRIBUTE" in ctx
        assert "Honesty over theater" in ctx
        # ceo (the default hat) is listed first.
        assert ctx.index("Founder") < ctx.index("Marketing")

    @pytest.mark.asyncio
    async def test_roster_empty_when_no_roles(self) -> None:
        assert (
            await build_role_roster_context(
                role_manager=_FakeRM([]), ledger=None, company_id=None
            )
            == ""
        )

    @pytest.mark.asyncio
    async def test_roster_none_manager_is_empty(self) -> None:
        assert (
            await build_role_roster_context(
                role_manager=None, ledger=None, company_id=None
            )
            == ""
        )

    @pytest.mark.asyncio
    async def test_roster_lands_in_system_prompt(self) -> None:
        from core.planner import build_system_prompt

        rm = _FakeRM([_CEO, _MARKETING])
        ctx = await build_role_roster_context(
            role_manager=rm, ledger=None, company_id=None
        )
        prompt = build_system_prompt(role_roster_context=ctx, goals_enabled=True)
        assert "<org_roles>" in prompt
        # Absent param → no roster (no leakage into non-ABE prompts).
        assert "<org_roles>" not in build_system_prompt(goals_enabled=True)


# ── protocol carries the badge fields ──────────────────────────────────


class TestProtocolRoleFields:
    def test_role_fields_present_when_set(self) -> None:
        m = response_message(
            "s",
            "hi",
            role_name="marketing",
            role_title="Head of Marketing",
            role_emoji="📣",
        )
        assert m.data["role_name"] == "marketing"
        assert m.data["role_title"] == "Head of Marketing"
        assert m.data["role_emoji"] == "📣"

    def test_role_fields_omitted_when_empty(self) -> None:
        m = response_message("s", "hi")
        assert "role_title" not in m.data
        assert "role_emoji" not in m.data
        assert "role_name" not in m.data
