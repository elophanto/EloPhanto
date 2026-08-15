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


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Verdicts persist across calls by design; tests must not share them."""
    wo.clear_exit_verification_cache()
    yield
    wo.clear_exit_verification_cache()


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


class TestOneProofCoversTheSweep:
    """14 brands through one exit need one proof, not 14.

    Also the optics: to an operator who has watched an agent loop on
    IP-checker pages, a geo check before every brand is indistinguishable
    from that loop ("WHY THE HELL IS IT CHECKING THE PROXY AGAIN").
    """

    @pytest.mark.asyncio
    async def test_second_call_reuses_the_verified_session(self, monkeypatch) -> None:
        calls = {"n": 0}

        async def geo(proxy_url, **kw):
            calls["n"] += 1
            return {"ip": "72.1.1.1", "state_code": "FL", "state_name": "florida", "service": "x"}

        monkeypatch.setattr(wo, "_egress_geo", geo)
        url = "http://u:pw_state-florida@h:1"
        ok1, pinned1, d1 = await wo.verify_exit_state(url, "FL")
        ok2, pinned2, d2 = await wo.verify_exit_state(url, "FL")

        assert ok1 and ok2
        assert calls["n"] == 1, "the sweep re-proved an already-proven exit"
        assert pinned2 == pinned1, "brands must share the verified session"
        assert d2.get("cached") is True

    @pytest.mark.asyncio
    async def test_failures_are_not_cached_on_the_http_path(self, monkeypatch) -> None:
        """Each retry re-rolls the exit, so the next call may honestly land."""
        seq = [
            {"ip": "1.1.1.1", "state_code": "VA", "state_name": "virginia", "service": "x"},
            {"ip": "72.2.2.2", "state_code": "FL", "state_name": "florida", "service": "x"},
        ]

        async def geo(proxy_url, **kw):
            return seq.pop(0)

        monkeypatch.setattr(wo, "_egress_geo", geo)
        url = "http://u:pw_state-florida@h:1"
        ok1, _, _ = await wo.verify_exit_state(url, "FL", attempts=1)
        ok2, _, _ = await wo.verify_exit_state(url, "FL", attempts=1)
        assert ok1 is False and ok2 is True

    @pytest.mark.asyncio
    async def test_an_expired_verdict_is_reproven(self, monkeypatch) -> None:
        calls = {"n": 0}

        async def geo(proxy_url, **kw):
            calls["n"] += 1
            return {"ip": "72.1.1.1", "state_code": "FL", "state_name": "florida", "service": "x"}

        monkeypatch.setattr(wo, "_egress_geo", geo)
        url = "http://u:pw_state-florida@h:1"
        await wo.verify_exit_state(url, "FL")
        key = (url, "FL")
        expires, pinned, detail = wo._exit_verify_cache[key]
        wo._exit_verify_cache[key] = (0.0, pinned, detail)  # force expiry
        await wo.verify_exit_state(url, "FL")
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_a_different_state_is_a_different_proof(self, monkeypatch) -> None:
        async def geo(proxy_url, **kw):
            return {"ip": "72.1.1.1", "state_code": "FL", "state_name": "florida", "service": "x"}

        monkeypatch.setattr(wo, "_egress_geo", geo)
        await wo.verify_exit_state("http://u:pw_state-florida@h:1", "FL")
        ok, _, _ = await wo.verify_exit_state("http://u:pw_state-texas@h:1", "TX", attempts=1)
        assert ok is False  # FL verdict must not vouch for a TX claim

    @pytest.mark.asyncio
    async def test_browser_verdicts_cache_including_brief_failure(self, monkeypatch) -> None:
        """A wrong browser exit must not mean one visible ipwho.is visit per
        brand — that is the checker-loop optics this exists to end."""
        calls = {"n": 0}

        async def fake_browser(bm, url, **kw):
            calls["n"] += 1
            return ('{"ip": "9.9.9.9", "region_code": "VA", "region": "Virginia"}', None)

        monkeypatch.setattr(wo, "fetch_page_via_browser", fake_browser)
        ok1, _ = await wo.verify_browser_exit(object(), "FL")
        ok2, d2 = await wo.verify_browser_exit(object(), "FL")
        assert ok1 is False and ok2 is False
        assert calls["n"] == 1 and d2.get("cached") is True
