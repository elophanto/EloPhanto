"""A `geo_state` stamp is proven, not assumed.

Routing through a state-targeted proxy *asks* to be in that state; it does
not prove it. Residential targeting is best-effort — sampled 2026-08-15,
`_state-texas` exited in Virginia half the time — and a rotating pool hands
each request a different city, so a geo check on one request says nothing
about the next. So the exit is pinned to one IP (a sticky session), that IP
is geolocated, and only a match lets the state be stamped. No verified exit,
no stamp — the observation is refused, never quietly downgraded.
"""

from __future__ import annotations

import pytest

import core.watch_observe as wo


class TestPinSession:
    def test_appends_a_sticky_token_to_a_geo_password(self) -> None:
        url = "http://u:pw_country-us_state-florida@geo.iproyal.com:12321"
        pinned = wo.pin_session(url, session="abcd1234")
        assert pinned == (
            "http://u:pw_country-us_state-florida_session-abcd1234_lifetime-30m"
            "@geo.iproyal.com:12321"
        )

    def test_is_idempotent(self) -> None:
        url = "http://u:pw_state-nevada@h:1"
        once = wo.pin_session(url, session="s1")
        assert wo.pin_session(once) == once  # already has _session-

    def test_leaves_a_plain_password_untouched(self) -> None:
        """Another provider's credentials must never be rewritten."""
        url = "http://u:plainsecret@proxy.other.com:8080"
        assert wo.pin_session(url) == url
        assert not wo.is_session_pinnable(url)

    def test_random_session_each_time(self) -> None:
        url = "http://u:pw_state-texas@h:1"
        a, b = wo.pin_session(url), wo.pin_session(url)
        assert a != b  # a re-roll of the exit, not the same one


class TestVerifyExitState:
    @pytest.mark.asyncio
    async def test_passes_when_the_exit_is_in_the_state(self, monkeypatch) -> None:
        async def geo(proxy_url, **kw):
            return {
                "ip": "72.179.1.1",
                "state_code": "TX",
                "state_name": "texas",
                "service": "ipwho.is",
            }

        monkeypatch.setattr(wo, "_egress_geo", geo)
        ok, url, detail = await wo.verify_exit_state("http://u:pw_state-texas@h:1", "TX")
        assert ok and detail["verified"] is True
        assert detail["ip"] == "72.179.1.1"
        assert "_session-" in url  # fetch through the pinned exit, not the original

    @pytest.mark.asyncio
    async def test_refuses_when_the_exit_is_elsewhere(self, monkeypatch) -> None:
        """The exact failure: asked Texas, IPRoyal delivered Virginia."""

        async def geo(proxy_url, **kw):
            return {
                "ip": "170.124.1.1",
                "state_code": "VA",
                "state_name": "virginia",
                "service": "ipwho.is",
            }

        monkeypatch.setattr(wo, "_egress_geo", geo)
        ok, url, detail = await wo.verify_exit_state(
            "http://u:pw_state-texas@h:1", "TX", attempts=3
        )
        assert ok is False and detail["verified"] is False
        assert len(detail["landed"]) == 3  # retried, each a fresh exit
        assert detail["landed"][0]["state_code"] == "VA"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds_on_a_later_roll(self, monkeypatch) -> None:
        seq = [
            {"ip": "1.1.1.1", "state_code": "VA", "state_name": "virginia", "service": "x"},
            {"ip": "72.179.1.1", "state_code": "FL", "state_name": "florida", "service": "x"},
        ]

        async def geo(proxy_url, **kw):
            return seq.pop(0)

        monkeypatch.setattr(wo, "_egress_geo", geo)
        ok, _url, detail = await wo.verify_exit_state(
            "http://u:pw_state-florida@h:1", "FL", attempts=3
        )
        assert ok and detail["attempts"] == 2

    @pytest.mark.asyncio
    async def test_unreachable_geolocation_is_a_refusal_not_a_pass(self, monkeypatch) -> None:
        """'Could not verify' must never soften into 'verified'."""

        async def geo(proxy_url, **kw):
            return None

        monkeypatch.setattr(wo, "_egress_geo", geo)
        ok, _url, detail = await wo.verify_exit_state("http://u:pw_state-fl@h:1", "FL")
        assert ok is False
        assert all(g.get("error") for g in detail["landed"])

    @pytest.mark.asyncio
    async def test_non_pinnable_proxy_gets_a_single_attempt(self, monkeypatch) -> None:
        calls = {"n": 0}

        async def geo(proxy_url, **kw):
            calls["n"] += 1
            return {"ip": "9.9.9.9", "state_code": "VA", "state_name": "virginia", "service": "x"}

        monkeypatch.setattr(wo, "_egress_geo", geo)
        ok, _url, _d = await wo.verify_exit_state("http://u:plainpw@h:1", "TX", attempts=3)
        assert ok is False and calls["n"] == 1  # retrying an unpinned URL is theatre


class TestParsingGeo:
    def test_resolves_state_name_to_code(self) -> None:
        got = wo._parse_geo_fields("1.2.3.4", "", "Florida", "svc")
        assert got and got["state_code"] == "FL"

    def test_needs_both_ip_and_state(self) -> None:
        assert wo._parse_geo_fields("", "FL", "florida", "svc") is None
        assert wo._parse_geo_fields("1.2.3.4", "", "Atlantis", "svc") is None
