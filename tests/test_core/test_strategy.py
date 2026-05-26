"""Strategy + Blocker model + StrategyManager (ABE Phase 11).

Locks in:
- Blocker.from_dict / as_dict round-trip
- load_strategy: missing file → None; malformed YAML → None;
  non-mapping top level → None; valid YAML round-trips with
  camelCase → snake_case key port
- StrategyManager: write_proposal versions by ISO timestamp;
  promote_proposal copies proposed → active + archives prior active;
  has_active / blocker_count
- save_blockers / load_blockers round-trip
"""

from __future__ import annotations

import time

from core.strategy import (
    Blocker,
    Strategy,
    StrategyManager,
    active_path,
    archive_dir,
    load_blockers,
    load_strategy,
    proposed_dir,
    save_blockers,
)


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestBlocker:
    def test_round_trip(self) -> None:
        b = Blocker(
            id="b001",
            type="missing_tool",
            description="LinkedIn poster missing",
            affected_tactics=["t1", "t3"],
            resolution_proposal="build",
            build_method="self_create_plugin",
            build_hint="Selenium-based LinkedIn poster",
        )
        d = b.as_dict()
        b2 = Blocker.from_dict(d)
        assert b2.id == b.id
        assert b2.type == b.type
        assert b2.affected_tactics == b.affected_tactics
        assert b2.resolution_proposal == b.resolution_proposal
        assert b2.build_method == b.build_method
        assert b2.is_resolved() is False

    def test_resolved(self) -> None:
        b = Blocker(id="b002", type="missing_vault_credential", description="x")
        assert b.is_resolved() is False
        b.resolved_at = "2026-05-26T10:00:00+00:00"
        assert b.is_resolved() is True


class TestLoadStrategy:
    def test_missing(self, tmp_path) -> None:
        assert load_strategy(tmp_path, "no-such") is None

    def test_bad_yaml(self, tmp_path) -> None:
        _write(active_path(tmp_path, "co"), "this: is: not: valid: yaml:")
        assert load_strategy(tmp_path, "co") is None

    def test_not_mapping(self, tmp_path) -> None:
        _write(active_path(tmp_path, "co"), "- just\n- a\n- list\n")
        assert load_strategy(tmp_path, "co") is None

    def test_round_trip_camel_to_snake(self, tmp_path) -> None:
        _write(
            active_path(tmp_path, "co"),
            """
strategyName: AlphaScala Voice
tagline: A test plan
positioningStatement: For X, AlphaScala is the Y that Z
audienceSegments:
  - name: founders
    whoTheyAre: tech founders
tactics:
  - priority: 1
    name: Daily X posts
    channel: twitter
creativeDirections:
  - angleName: Founder POV
    hookTemplates:
      - "POV: <scenario>"
vault_requirements:
  - key: twitter_session
    needed_for_tactics: [t1]
    resolution_proposal: ask
tool_requirements: []
voice_seed:
  hookTemplates: ["POV: <scenario>"]
  banned_phrases: [leverage]
execution_priority: staged
""",
        )
        s = load_strategy(tmp_path, "co")
        assert s is not None
        assert s.strategy_name == "AlphaScala Voice"
        assert s.tagline == "A test plan"
        assert s.audience_segments[0]["name"] == "founders"
        assert s.tactics[0]["channel"] == "twitter"
        assert s.creative_directions[0]["hookTemplates"] == ["POV: <scenario>"]
        assert s.vault_requirements[0]["key"] == "twitter_session"
        assert s.voice_seed["banned_phrases"] == ["leverage"]
        assert s.execution_priority == "staged"


class TestStrategyManager:
    def test_write_proposal_versioned(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        p1 = mgr.write_proposal("co", {"strategyName": "v1"})
        time.sleep(1.05)  # ensure ISO timestamps differ to the second
        p2 = mgr.write_proposal("co", {"strategyName": "v2"})
        assert p1 != p2
        assert p1.is_file() and p2.is_file()
        assert p1.parent == proposed_dir(tmp_path, "co")
        proposals = mgr.list_proposed("co")
        assert len(proposals) == 2

    def test_promote_no_prior(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        prop = mgr.write_proposal("co", {"strategyName": "first"})
        new_active, archived = mgr.promote_proposal("co", prop)
        assert new_active == active_path(tmp_path, "co")
        assert new_active.is_file()
        assert archived is None
        # cache invalidated
        s = mgr.get_active("co")
        assert s is not None
        assert s.strategy_name == "first"

    def test_promote_archives_prior(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        p1 = mgr.write_proposal("co", {"strategyName": "v1"})
        mgr.promote_proposal("co", p1)
        time.sleep(1.05)
        p2 = mgr.write_proposal("co", {"strategyName": "v2"})
        new_active, archived = mgr.promote_proposal("co", p2)
        assert new_active.is_file()
        assert archived is not None
        assert archived.is_file()
        assert archived.parent == archive_dir(tmp_path, "co")
        # Active now points at v2
        s = mgr.get_active("co")
        assert s.strategy_name == "v2"

    def test_has_active_false_when_missing(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        assert mgr.has_active("co") is False

    def test_blocker_count(self, tmp_path) -> None:
        mgr = StrategyManager(tmp_path)
        assert mgr.blocker_count("co") == 0
        bs = [
            Blocker(id="b1", type="missing_tool", description="x"),
            Blocker(id="b2", type="missing_tool", description="y"),
        ]
        bs[0].resolved_at = "2026-05-26T10:00:00+00:00"
        save_blockers(tmp_path, "co", bs)
        # 1 unresolved
        assert mgr.blocker_count("co") == 1

    def test_no_project_root(self) -> None:
        mgr = StrategyManager(None)
        assert mgr.get_active("co") is None
        assert mgr.has_active("co") is False
        assert mgr.blocker_count("co") == 0


class TestBlockersIO:
    def test_save_load_round_trip(self, tmp_path) -> None:
        bs = [
            Blocker(
                id="b1",
                type="missing_tool",
                description="LinkedIn",
                resolution_proposal="build",
                build_method="self_create_plugin",
                build_hint="Selenium impl",
            ),
            Blocker(
                id="b2",
                type="missing_vault_credential",
                description="SMTP",
                resolution_proposal="ask",
            ),
        ]
        save_blockers(tmp_path, "co", bs)
        loaded = load_blockers(tmp_path, "co")
        assert len(loaded) == 2
        assert loaded[0].id == "b1"
        assert loaded[0].build_method == "self_create_plugin"
        assert loaded[1].resolution_proposal == "ask"

    def test_load_missing(self, tmp_path) -> None:
        assert load_blockers(tmp_path, "co") == []


def test_strategy_dataclass_defaults() -> None:
    s = Strategy()
    assert s.strategy_name == ""
    assert s.tactics == []
    assert s.voice_seed == {}
    assert s.execution_priority == "staged"
