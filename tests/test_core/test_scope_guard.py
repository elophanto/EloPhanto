"""Self-owned-scope guard — the boundary between "my system" and someone else's.

The property under test is narrow and load-bearing: an agent with
authenticated HTTP and stored credentials can reach endpoints that are not
its operator's to change, and no amount of caller authentication tells it
apart. These tests pin the asymmetry — reads free, writes cautious,
destructive-on-foreign refused outright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.scope_guard import (
    ActionKind,
    Authorization,
    ScopeGuard,
    ScopePolicy,
    TargetScope,
)


class TestClassification:
    def test_declared_host_is_owned(self) -> None:
        guard = ScopeGuard(owned=["api.mygym.example"])
        assert guard.classify("https://api.mygym.example/v1") == TargetScope.OWNED

    def test_subdomain_of_declared_domain_is_owned(self) -> None:
        guard = ScopeGuard(owned=["mycompany.com"])
        assert guard.classify("https://api.mycompany.com/x") == TargetScope.OWNED

    def test_glob_pattern_matches(self) -> None:
        guard = ScopeGuard(owned=["*.mycompany.com"])
        assert guard.classify("https://api.mycompany.com/x") == TargetScope.OWNED

    def test_undeclared_host_is_unknown(self) -> None:
        guard = ScopeGuard(owned=["api.mygym.example"])
        assert guard.classify("https://api.other.example") == TargetScope.UNKNOWN

    def test_strict_unknown_treats_undeclared_as_third_party(self) -> None:
        guard = ScopeGuard(policy=ScopePolicy(strict_unknown=True))
        assert guard.classify("https://api.other.example") == TargetScope.THIRD_PARTY


class TestActionClassification:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_safe_methods_are_reads(self, method: str) -> None:
        assert ScopeGuard().classify_action(method, "/x") == ActionKind.READ

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
    def test_mutating_methods_are_writes(self, method: str) -> None:
        assert ScopeGuard().classify_action(method, "/x") == ActionKind.WRITE

    def test_delete_is_destructive(self) -> None:
        assert ScopeGuard().classify_action("DELETE", "/x") == ActionKind.DESTRUCTIVE

    def test_destructive_path_overrides_benign_method(self) -> None:
        # Plenty of APIs delete via POST; the verb alone is not enough.
        guard = ScopeGuard()
        assert guard.classify_action("POST", "/v1/users/42/delete") == (
            ActionKind.DESTRUCTIVE
        )
        assert guard.classify_action("POST", "/account/revoke") == (
            ActionKind.DESTRUCTIVE
        )


class TestForeignAccountDetection:
    def test_numeric_user_id_reads_as_foreign(self) -> None:
        assert ScopeGuard().targets_foreign_account("/api/users/8813")

    def test_self_reference_is_not_foreign(self) -> None:
        guard = ScopeGuard()
        assert not guard.targets_foreign_account("/api/users/me")
        assert not guard.targets_foreign_account("/api/users/me/bookings")
        assert not guard.targets_foreign_account("/account/self/settings")

    def test_plain_resource_path_is_not_foreign(self) -> None:
        assert not ScopeGuard().targets_foreign_account("/v1/bookings/17")


class TestVerdicts:
    def test_reads_always_allowed_without_approval(self) -> None:
        verdict = ScopeGuard().assess("https://api.other.example/v1/x", "GET", "/v1/x")
        assert verdict.allowed
        assert not verdict.requires_approval

    def test_write_to_owned_system_needs_no_approval(self) -> None:
        guard = ScopeGuard(owned=["api.mygym.example"])
        verdict = guard.assess(
            "https://api.mygym.example/v1/bookings", "POST", "/v1/bookings"
        )
        assert verdict.allowed
        assert not verdict.requires_approval

    def test_destructive_on_owned_system_asks(self) -> None:
        guard = ScopeGuard(owned=["api.mygym.example"])
        verdict = guard.assess(
            "https://api.mygym.example/v1/bookings/9", "DELETE", "/v1/bookings/9"
        )
        assert verdict.allowed
        assert verdict.requires_approval

    def test_write_to_undeclared_system_asks(self) -> None:
        verdict = ScopeGuard().assess(
            "https://api.other.example/v1/things", "POST", "/v1/things"
        )
        assert verdict.allowed
        assert verdict.requires_approval

    def test_destructive_on_undeclared_system_is_refused(self) -> None:
        verdict = ScopeGuard().assess(
            "https://api.other.example/v1/things/1", "DELETE", "/v1/things/1"
        )
        assert not verdict.allowed
        assert "not a system you have declared" in verdict.reason

    def test_destructive_on_another_persons_record_is_refused_not_prompted(
        self,
    ) -> None:
        """The case this module exists for.

        An approval dialog is not an authorization to destroy a third
        party's data, so this must refuse outright rather than ask.
        """
        verdict = ScopeGuard().assess(
            "https://api.gym.example/v1/users/8813", "DELETE", "/v1/users/8813"
        )
        assert not verdict.allowed
        assert not verdict.requires_approval
        assert "another person's record" in verdict.reason

    def test_owned_system_does_not_license_touching_other_users(self) -> None:
        """Owning the host is not owning everyone's record on it."""
        guard = ScopeGuard(owned=["api.mygym.example"])
        verdict = guard.assess(
            "https://api.mygym.example/v1/members/551", "DELETE", "/v1/members/551"
        )
        assert not verdict.allowed


class TestAuthorizations:
    def test_recorded_authorization_permits_a_scoped_action(self) -> None:
        guard = ScopeGuard(
            authorizations=[
                Authorization(
                    target="staging.client.example",
                    scope="DELETE /api/test-fixtures/*",
                    authorized_by="Jane Doe, CTO",
                    expires="2099-12-31",
                )
            ]
        )
        verdict = guard.assess(
            "https://staging.client.example/api/test-fixtures/7",
            "DELETE",
            "/api/test-fixtures/7",
        )
        assert verdict.allowed
        assert verdict.requires_approval  # still confirms
        assert verdict.authorization is not None

    def test_authorization_does_not_cover_out_of_scope_paths(self) -> None:
        guard = ScopeGuard(
            authorizations=[
                Authorization(
                    target="staging.client.example",
                    scope="DELETE /api/test-fixtures/*",
                    expires="2099-12-31",
                )
            ]
        )
        verdict = guard.assess(
            "https://staging.client.example/api/customers/12",
            "DELETE",
            "/api/customers/12",
        )
        assert not verdict.allowed

    def test_expired_authorization_does_not_apply(self) -> None:
        guard = ScopeGuard(
            authorizations=[
                Authorization(
                    target="staging.client.example",
                    scope="DELETE /*",
                    expires="2020-01-01",
                )
            ]
        )
        verdict = guard.assess(
            "https://staging.client.example/api/x", "DELETE", "/api/x"
        )
        assert not verdict.allowed

    def test_blank_scope_is_not_a_blank_cheque(self) -> None:
        auth = Authorization(target="x.example", scope="", expires="2099-01-01")
        assert not auth.covers("DELETE", "/anything")


class TestPersistence:
    def test_load_missing_file_yields_empty_but_still_strict(
        self, tmp_path: Path
    ) -> None:
        guard = ScopeGuard.load(tmp_path)
        assert guard.owned == []
        verdict = guard.assess("https://api.x.example/y", "DELETE", "/y")
        assert not verdict.allowed

    def test_round_trip(self, tmp_path: Path) -> None:
        guard = ScopeGuard(owned=["api.mygym.example"])
        guard.declare_owned("shop.mine.example")
        guard.save(tmp_path)

        reloaded = ScopeGuard.load(tmp_path)
        assert "api.mygym.example" in reloaded.owned
        assert "shop.mine.example" in reloaded.owned
        assert reloaded.classify("https://shop.mine.example/x") == TargetScope.OWNED

    def test_corrupt_file_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / "owned_scope.yaml").write_text("{{{not yaml", encoding="utf-8")
        guard = ScopeGuard.load(tmp_path)
        # Nothing is owned, so destructive foreign actions stay refused.
        assert guard.owned == []
        assert not guard.assess("https://x.example/y", "DELETE", "/y").allowed
