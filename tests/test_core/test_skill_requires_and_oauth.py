"""Skill requirement contracts and the OAuth token store.

Skills: a playbook that drives a CLI is only useful when that CLI exists,
so the manifest declares it and the host is checked before the skill is
offered.

OAuth: refresh tokens are the crown jewels of a delegated grant. They are
persisted, refreshed transparently, and never handed out — the broker only
ever sees an access token.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.oauth import OAuthTokenStore, TokenSet
from core.skills import SkillManager


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "") -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n## Description\n\n{body or name}\n",
        encoding="utf-8",
    )


class TestSkillRequires:
    def test_block_form_requires_is_parsed(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "trello-like",
            "description: demo\n"
            "requires:\n"
            "  bins: [curl, jq]\n"
            "  env: [DEMO_TOKEN]\n"
            "  credentials: [demo]\n"
            "primary_env: DEMO_TOKEN\n"
            "install:\n"
            "  brew: jq",
        )
        manager = SkillManager(tmp_path)
        manager.discover()
        skill = manager.get_skill("trello-like")

        assert skill is not None
        assert skill.requires_bins == ["curl", "jq"]
        assert skill.requires_env == ["DEMO_TOKEN"]
        assert skill.requires_credentials == ["demo"]
        assert skill.primary_env == "DEMO_TOKEN"
        assert skill.install == {"brew": "jq"}

    def test_shorthand_list_form_means_binaries(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "short", "description: d\nrequires: [ffmpeg]")
        manager = SkillManager(tmp_path)
        manager.discover()
        assert manager.get_skill("short").requires_bins == ["ffmpeg"]

    def test_legacy_inline_fields_still_work(self, tmp_path: Path) -> None:
        """The 178 existing skills must keep parsing unchanged."""
        _write_skill(
            tmp_path,
            "legacy",
            "description: legacy skill\ntriggers: [alpha, beta]\n"
            "requires_tools: [browser_navigate]",
        )
        manager = SkillManager(tmp_path)
        manager.discover()
        skill = manager.get_skill("legacy")
        assert skill.requires_tools == ["browser_navigate"]
        assert "alpha" in skill.triggers

    def test_malformed_frontmatter_does_not_lose_the_skill(
        self, tmp_path: Path
    ) -> None:
        directory = tmp_path / "broken"
        directory.mkdir()
        (directory / "SKILL.md").write_text(
            "---\ndescription: [unclosed\n---\n\n## Description\n\nstill here\n",
            encoding="utf-8",
        )
        manager = SkillManager(tmp_path)
        manager.discover()
        assert manager.get_skill("broken") is not None

    def test_missing_requirements_are_reported_with_install_hints(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_skill(
            tmp_path,
            "needs-stuff",
            "description: d\n"
            "requires:\n"
            "  bins: [definitely-not-a-real-binary-xyz]\n"
            "  env: [DEFINITELY_UNSET_XYZ]\n"
            "install:\n"
            "  brew: something",
        )
        monkeypatch.delenv("DEFINITELY_UNSET_XYZ", raising=False)
        manager = SkillManager(tmp_path)
        manager.discover()
        missing = manager.get_skill("needs-stuff").missing_requirements()

        assert any("definitely-not-a-real-binary-xyz" in m for m in missing)
        assert any("brew: something" in m for m in missing)
        assert any("DEFINITELY_UNSET_XYZ" in m for m in missing)

    def test_check_host_hides_a_skill_whose_binary_is_absent(
        self, tmp_path: Path
    ) -> None:
        _write_skill(
            tmp_path,
            "unusable",
            "description: d\nrequires:\n  bins: [definitely-not-a-real-binary-xyz]",
        )
        manager = SkillManager(tmp_path)
        manager.discover()
        skill = manager.get_skill("unusable")

        assert skill.is_available(set())  # cheap path unchanged
        assert not skill.is_available(set(), check_host=True)

    def test_credential_gate(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path, "needs-cred", "description: d\nrequires:\n  credentials: [gmail]"
        )
        manager = SkillManager(tmp_path)
        manager.discover()
        skill = manager.get_skill("needs-cred")

        assert not skill.is_available(set(), available_credentials=set())
        assert skill.is_available(set(), available_credentials={"gmail"})


class TestOAuthTokenStore:
    def test_round_trip_through_disk(self, tmp_path: Path) -> None:
        store = OAuthTokenStore(tmp_path)
        store.save(
            "google",
            TokenSet(
                access_token="at-1",
                refresh_token="rt-1",
                expires_at=0.0,
                account="me@example.com",
            ),
        )
        reloaded = OAuthTokenStore(tmp_path)
        tokens = reloaded.get("google")
        assert tokens is not None
        assert tokens.access_token == "at-1"
        assert tokens.account == "me@example.com"

    def test_redacted_view_hides_the_tokens(self, tmp_path: Path) -> None:
        store = OAuthTokenStore(tmp_path)
        store.save(
            "google", TokenSet(access_token="at-secret", refresh_token="rt-secret")
        )
        rendered = str(store.list_providers())
        assert "at-secret" not in rendered
        assert "rt-secret" not in rendered
        assert store.list_providers()["google"]["has_refresh_token"] is True

    def test_expiry_detection(self) -> None:
        import time

        assert TokenSet(expires_at=time.time() - 10).is_expired()
        assert not TokenSet(expires_at=time.time() + 3600).is_expired()
        # No advertised expiry means treat as long-lived.
        assert not TokenSet(expires_at=0.0).is_expired()

    def test_expired_token_without_refresh_returns_none(self, tmp_path: Path) -> None:
        import time

        store = OAuthTokenStore(tmp_path)
        store.save(
            "google", TokenSet(access_token="stale", expires_at=time.time() - 100)
        )
        assert store.access_token("google") is None

    def test_unknown_provider_returns_none(self, tmp_path: Path) -> None:
        assert OAuthTokenStore(tmp_path).access_token("nope") is None

    def test_forget_removes_the_grant(self, tmp_path: Path) -> None:
        store = OAuthTokenStore(tmp_path)
        store.save("google", TokenSet(access_token="a"))
        assert store.forget("google")
        assert not store.forget("google")
        assert OAuthTokenStore(tmp_path).get("google") is None

    def test_file_permissions_are_owner_only(self, tmp_path: Path) -> None:
        import stat

        store = OAuthTokenStore(tmp_path)
        store.save("google", TokenSet(access_token="a", refresh_token="r"))
        mode = (tmp_path / "oauth_tokens.json").stat().st_mode
        assert not (mode & stat.S_IRGRP), "group must not read the token store"
        assert not (mode & stat.S_IROTH), "others must not read the token store"
