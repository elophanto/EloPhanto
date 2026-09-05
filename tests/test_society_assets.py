"""Startup graphics build is opt-in, cached, and independent of CLI execution."""

import json
from pathlib import Path
from unittest.mock import patch

from core.society_assets import prepare_society, runtime_config_path, source_fingerprint


def test_only_runtime_commands_prepare_graphics(monkeypatch):
    monkeypatch.delenv("ELOPHANTO_CONFIG", raising=False)
    assert runtime_config_path([]) == Path("config.yaml")
    assert runtime_config_path(["chat", "--config", "personal.yaml"]) == Path("personal.yaml")
    assert runtime_config_path(["gateway", "--config=other.yaml"]) == Path("other.yaml")
    for args in [["doctor"], ["vault", "list"], ["chat", "--help"], ["--help"], ["daemon"]]:
        assert runtime_config_path(args) is None
    monkeypatch.setenv("ELOPHANTO_CONFIG", "custom.yaml")
    assert runtime_config_path(["--web"]) == Path("custom.yaml")


def make_project(root: Path, enabled: bool):
    (root / "config.yaml").write_text(f"society:\n  enabled: {str(enabled).lower()}\n")
    web = root / "web"
    (web / "src").mkdir(parents=True)
    (web / "src" / "scene.ts").write_text("scene v1")
    (web / "dist").mkdir()
    (web / "dist" / "index.html").write_text("built")
    (web / "package.json").write_text("{}")
    return web


def test_disabled_never_invokes_frontend(tmp_path):
    make_project(tmp_path, False)
    with patch("core.society_assets.subprocess.run") as run:
        assert prepare_society([], tmp_path)
        run.assert_not_called()


def test_cached_build_skips_npm_and_source_changes_invalidate(tmp_path):
    web = make_project(tmp_path, True)
    signature = source_fingerprint(web)
    (web / "dist" / ".society-build.json").write_text(json.dumps({"source": signature}))
    with patch("core.society_assets.subprocess.run") as run:
        assert prepare_society([], tmp_path)
        run.assert_not_called()
    (web / "src" / "scene.ts").write_text("scene v2")
    assert source_fingerprint(web) != signature


def test_build_failure_leaves_old_stamp_and_does_not_raise(tmp_path):
    web = make_project(tmp_path, True)
    with (
        patch("core.society_assets.shutil.which", return_value="/usr/bin/npm"),
        patch("core.society_assets.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        run.return_value.stdout = "build failed"
        run.return_value.stderr = ""
        assert not prepare_society([], tmp_path)
    assert not (web / "dist" / ".society-build.json").exists()


def test_profile_override_enables_build(tmp_path):
    make_project(tmp_path, False)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "visual.yaml").write_text(
        "config_overrides:\n  society:\n    enabled: true\n"
    )
    with patch("core.society_assets.shutil.which", return_value=None):
        assert not prepare_society(["chat", "--profile", "visual"], tmp_path)
