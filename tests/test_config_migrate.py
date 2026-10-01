"""``elophanto config migrate`` — additive keys and value rewrites."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from cli.config_cmd import (
    _MIGRATIONS,
    _REWRITES,
    _apply_migration,
    _pending_migrations,
    _retired_models_apply,
    _retired_models_pending,
    config_cmd,
)

_OLD = """agent:
  name: EloPhanto
  pre_action_review: false
llm:
  providers:
    codex:
      enabled: true
      default_model: "gpt-5.5"   # subscription
    openai:
      enabled: false
      default_model: "gpt-5.5"
  vision_model: "codex/gpt-5.5"
  routing:
    planning:
      preferred_provider: codex
      models:
        codex: "gpt-5.5"
        openai: "gpt-5.5"
    simple:
      models:
        codex: gpt-5.5-mini
  budget:
    daily_limit_usd: 10
browser:
  vision_model: codex/gpt-5.5
goals:
  enabled: true
  round_robin: true
# a top-level comment
autonomous_mind:
  enabled: false
"""


def _by_id(mid: str):
    return next(m for m in _MIGRATIONS if m.id == mid)


def test_rewrite_replaces_every_gpt55_model_id() -> None:
    assert _retired_models_pending(yaml.safe_load(_OLD))
    out = _retired_models_apply(_OLD)
    cfg = yaml.safe_load(out)
    llm = cfg["llm"]
    assert llm["providers"]["codex"]["default_model"] == "gpt-6.1-sol"
    assert llm["providers"]["openai"]["default_model"] == "gpt-6.1-sol"
    assert llm["routing"]["planning"]["models"] == {
        "codex": "gpt-6.1-sol",
        "openai": "gpt-6.1-sol",
    }
    assert llm["routing"]["simple"]["models"]["codex"] == "gpt-6-luna"
    assert llm["vision_model"] == "codex/gpt-6.1-sol"
    assert cfg["browser"]["vision_model"] == "codex/gpt-6.1-sol"
    assert "# subscription" in out
    assert "gpt-5.5" not in out
    assert not _retired_models_pending(cfg)
    # Idempotent.
    assert _retired_models_apply(out) == out


def test_rewrite_leaves_comments_free_text_and_lookalikes_alone() -> None:
    text = """llm:
  providers:
    codex:
      # gpt-5.5 retired 2026-10-14
      default_model: gpt-6.1-sol  # was gpt-5.5
    openai:
      default_model: "gpt-5.55"
  note: "we moved off gpt-5.5 last month"
  routing:
    simple:
      models:
        openrouter: openai/gpt-5.5-codex
"""
    assert not _retired_models_pending(yaml.safe_load(text))
    assert _retired_models_apply(text) == text


def test_rewrite_handles_list_items_and_openrouter_ids() -> None:
    text = """fallbacks:
  - gpt-5.5
  - "openai/gpt-5.5-mini"
"""
    out = _retired_models_apply(text)
    assert yaml.safe_load(out)["fallbacks"] == ["gpt-6.1-sol", "openai/gpt-6-luna"]


def test_nested_migration_goes_into_existing_routing() -> None:
    out = _apply_migration(_OLD, _by_id("deliberation-route-2026-09"))
    assert out.count("  routing:") == 1
    cfg = yaml.safe_load(out)
    route = cfg["llm"]["routing"]["deliberation"]
    assert route["reasoning_effort"] == "max"
    assert route["models"]["codex"] == "gpt-6.1-sol"
    # Siblings are intact, and it lands inside routing, before budget.
    assert set(cfg["llm"]["routing"]) == {"planning", "simple", "deliberation"}
    assert cfg["llm"]["budget"] == {"daily_limit_usd": 10}


def test_multi_key_migration_skips_keys_already_set() -> None:
    # round_robin is set, so the migration is not pending by its key path…
    assert _by_id("long-run-goals-2026-09") not in _pending_migrations(
        yaml.safe_load(_OLD)
    )
    # …and when forced, keys the operator set are not written twice.
    out = _apply_migration(_OLD, _by_id("long-run-goals-2026-09"))
    goals_lines = out.split("goals:", 1)[1].split("# a top-level comment", 1)[0]
    assert goals_lines.count("round_robin:") == 1
    cfg = yaml.safe_load(out)
    assert cfg["goals"]["round_robin"] is True
    assert cfg["goals"]["deliberate"] is True
    assert cfg["goals"]["health_digest_hour_utc"] == 7


def test_everything_the_operator_set_survives() -> None:
    text = _OLD
    for m in _pending_migrations(yaml.safe_load(text)):
        text = _apply_migration(text, m)
    for r in _REWRITES:
        text = r.apply(text)
    cfg = yaml.safe_load(text)
    assert cfg["agent"]["pre_action_review"] is False
    assert cfg["autonomous_mind"]["enabled"] is False
    assert cfg["autonomous_mind"]["deliberate"] is True
    assert "arbiter" in cfg["autonomous_mind"]
    assert not _pending_migrations(cfg)
    assert not any(r.pending(cfg) for r in _REWRITES)


def test_demo_config_needs_no_migration() -> None:
    demo = Path(__file__).resolve().parent.parent / "config.demo.yaml"
    cfg = yaml.safe_load(demo.read_text(encoding="utf-8"))
    assert [m.id for m in _pending_migrations(cfg)] == []
    assert not any(r.pending(cfg) for r in _REWRITES)


def test_cli_applies_and_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(_OLD, encoding="utf-8")
    result = CliRunner().invoke(config_cmd, ["migrate", "--config", str(path), "-y"])
    assert result.exit_code == 0, result.output
    assert "gpt-5.5-retired-2026-10" in result.output
    assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == _OLD
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert cfg["llm"]["providers"]["codex"]["default_model"] == "gpt-6.1-sol"
    assert cfg["llm"]["providers"]["openai"]["default_model"] == "gpt-6.1-sol"
    again = CliRunner().invoke(config_cmd, ["migrate", "--config", str(path), "-y"])
    assert "Up to date" in again.output
