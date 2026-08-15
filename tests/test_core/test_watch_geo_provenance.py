"""`geo_state` on evidence is a provenance claim, and it has to be true.

Found 2026-08-15 while the operator's proxy was pinned to Nevada. Before
this, `watch_observe geo_state=NV` with no NV pool entry fell back to
whatever the single proxy was — and with the proxy *disabled*, to the host's
own connection — then stamped the evidence "NV" regardless. The register
would have said "this is what a Nevada customer sees" about a page fetched
from the operator's desk. That is the one lie the whole organ exists to make
impossible.

Now: a specific-state request is served by a pool exit for that state, or by
the single proxy when it declares `proxy.state` to match — otherwise the
tool refuses, and says how to fix it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from core.config import ProxyConfig
from core.watch import WatchManager


@dataclass
class _Resp:
    content: str


class _Router:
    """Extracts one claim whose excerpt is on the page."""

    async def complete(self, **_kw: Any) -> _Resp:
        return _Resp(
            '{"claims": [{"subcriterion": "welcome", "claim": "Bonus 10,000 GC", '
            '"value_text": "10,000 GC", "excerpt": "Bonus 10,000 GC on signup"}]}'
        )


class _Cfg:
    def __init__(self, proxy: ProxyConfig) -> None:
        self.proxy = proxy


@pytest.fixture
async def wm(tmp_path):
    from core.database import Database

    db = Database(str(tmp_path / "geo.db"))
    await db.initialize()
    yield WatchManager(db)
    await db.close()


async def _seed(wm: WatchManager):
    subj = await wm.add_subject(name="Rival", company_id="c1", url="https://rival.example")
    await wm.upsert_dimension(
        name="Promos",
        company_id="c1",
        weight_pct=100,
        subcriteria=[{"name": "welcome", "weight_pct": 100}],
    )
    return subj


def _fake_pages(monkeypatch, seen: dict[str, Any]) -> None:
    """Fake the HTTP fetch that both watch_observe and watch_analyze go
    through, recording which proxy (if any) it was asked to use."""
    import core.watch_observe as wo

    async def fake_fetch(url, **kw):
        seen["proxy_url"] = kw.get("proxy_url")
        return ("Bonus 10,000 GC on signup " * 40, None)

    async def fake_collect(start_url, **kw):
        seen["proxy_url"] = kw.get("proxy_url")
        return [
            {
                "url": start_url,
                "text": "Bonus 10,000 GC on signup " * 40,
                "error": None,
                "method": "http",
            }
        ]

    monkeypatch.setattr(wo, "fetch_page", fake_fetch)
    monkeypatch.setattr(wo, "collect_pages", fake_collect)


async def _observe(wm, cfg, geo_state=None):
    from tools.watch.tools import WatchObserveTool

    t = WatchObserveTool()
    t._watch_manager = wm
    t._router = _Router()
    t._config = cfg
    params: dict[str, Any] = {"subject": "Rival", "dimension": "Promos", "company_id": "c1"}
    if geo_state:
        params["geo_state"] = geo_state
    return await t.execute(params)


def _patch_verify(monkeypatch, *, ok=True, ip="72.179.10.1", state="FL"):
    """Make exit verification deterministic and offline.

    The tools import verify_exit_state inside the call, so patching the
    module attribute is enough. Real routing is covered by the unit suite and
    the live smoke test; here we only care that the tools gate on the result.
    """
    import core.watch_observe as wo

    async def fake_verify(proxy_url, want, **kw):
        if ok:
            return (
                True,
                proxy_url,
                {
                    "ip": ip,
                    "state_code": state.upper(),
                    "state_name": "verified",
                    "verified": True,
                    "session_pinned": True,
                    "attempts": 1,
                },
            )
        return (
            False,
            proxy_url,
            {
                "verified": False,
                "wanted": want.upper(),
                "landed": [{"ip": "170.1.1.1", "state_code": "VA", "state_name": "virginia"}],
            },
        )

    async def fake_browser_verify(bm, want, **kw):
        if ok:
            return True, {"ip": ip, "state_code": state.upper(), "verified": True}
        return False, {"state_code": "VA", "verified": False}

    monkeypatch.setattr(wo, "verify_exit_state", fake_verify)
    monkeypatch.setattr(wo, "verify_browser_exit", fake_browser_verify)


class TestExitIsProvenBeforeStamping:
    @pytest.mark.asyncio
    async def test_verified_exit_is_recorded_on_every_row(self, wm, monkeypatch) -> None:
        await _seed(wm)
        _fake_pages(monkeypatch, {})
        _patch_verify(monkeypatch, ok=True, ip="72.179.10.1", state="FL")
        cfg = _Cfg(
            ProxyConfig(
                enabled=True,
                type="http",
                host="geo.example",
                port=12321,
                username="u",
                password="p_country-us_state-florida",
                state="FL",
            )
        )
        res = await _observe(wm, cfg, geo_state="FL")

        assert res.success, res.error
        assert res.data["exit"]["ip"] == "72.179.10.1"
        rows = await wm.list_evidence("c1")
        assert rows
        assert all(r.geo_state == "FL" and r.exit_ip == "72.179.10.1" for r in rows)

    @pytest.mark.asyncio
    async def test_exit_in_the_wrong_state_is_refused_and_writes_nothing(
        self, wm, monkeypatch
    ) -> None:
        """Asked Florida, the provider delivered Virginia — the real failure."""
        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        _patch_verify(monkeypatch, ok=False)
        cfg = _Cfg(
            ProxyConfig(
                enabled=True,
                type="http",
                host="geo.example",
                port=12321,
                username="u",
                password="p_state-florida",
                state="FL",
            )
        )
        res = await _observe(wm, cfg, geo_state="FL")

        assert not res.success
        assert "Exit verification failed" in res.error
        assert "VA (170.1.1.1)" in res.error
        assert "proxy_url" not in seen  # refused before fetching anything
        assert await wm.list_evidence("c1") == []

    @pytest.mark.asyncio
    async def test_no_state_claim_skips_verification_entirely(self, wm, monkeypatch) -> None:
        import core.watch_observe as wo

        called = {"n": 0}

        async def boom(*a, **k):
            called["n"] += 1
            return False, "", {}

        monkeypatch.setattr(wo, "verify_exit_state", boom)
        await _seed(wm)
        _fake_pages(monkeypatch, {})
        res = await _observe(wm, _Cfg(ProxyConfig(enabled=False)))

        assert res.success, res.error
        assert called["n"] == 0  # nothing to prove without a state claim
        rows = await wm.list_evidence("c1")
        assert rows and all(r.exit_ip == "" for r in rows)


class TestObserveRefusesAnUnroutableState:
    @pytest.mark.asyncio
    async def test_proxy_disabled_geo_state_is_refused_not_stamped(self, wm, monkeypatch) -> None:
        """The exact hole: proxy off, geo_state=NV → used to fetch direct and stamp NV."""
        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        res = await _observe(wm, _Cfg(ProxyConfig(enabled=False)), geo_state="NV")

        assert not res.success
        assert "No network exit for geo_state=NV" in res.error
        assert "proxy.state: NV" in res.error
        assert "proxy_url" not in seen  # nothing was fetched
        assert await wm.list_evidence("c1") == []  # and nothing was stamped

    @pytest.mark.asyncio
    async def test_single_proxy_of_unknown_state_is_refused_for_a_specific_state(
        self, wm, monkeypatch
    ) -> None:
        await _seed(wm)
        _fake_pages(monkeypatch, {})
        cfg = _Cfg(ProxyConfig(enabled=True, type="http", host="p.example", port=1))
        res = await _observe(wm, cfg, geo_state="NV")
        assert not res.success and "geo_state=NV" in res.error

    @pytest.mark.asyncio
    async def test_single_proxy_pinned_elsewhere_is_refused(self, wm, monkeypatch) -> None:
        """A Nevada exit must not serve a Texas claim."""
        await _seed(wm)
        _fake_pages(monkeypatch, {})
        cfg = _Cfg(ProxyConfig(enabled=True, type="http", host="p.example", port=1, state="NV"))
        res = await _observe(wm, cfg, geo_state="TX")
        assert not res.success and "geo_state=TX" in res.error


class TestObserveRoutesWhenItHonestlyCan:
    @pytest.mark.asyncio
    async def test_single_proxy_declaring_the_state_is_used_and_stamped(
        self, wm, monkeypatch
    ) -> None:
        """The operator's actual setup: one IPRoyal exit pinned to Nevada."""
        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        _patch_verify(monkeypatch, ok=True, ip="72.179.9.9", state="NV")
        cfg = _Cfg(
            ProxyConfig(
                enabled=True,
                type="http",
                host="geo.example",
                port=12321,
                username="u",
                password="p_country-us_state-nevada",
                state="NV",
            )
        )
        res = await _observe(wm, cfg, geo_state="NV")

        assert res.success, res.error
        assert res.data["proxied"] is True
        assert seen["proxy_url"] == "http://u:p_country-us_state-nevada@geo.example:12321"
        rows = await wm.list_evidence("c1")
        assert rows and all(r.geo_state == "NV" for r in rows)

    @pytest.mark.asyncio
    async def test_pool_entry_wins_over_the_single_proxy(self, wm, monkeypatch) -> None:
        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        _patch_verify(monkeypatch, ok=True, ip="72.16.1.1", state="TX")
        cfg = _Cfg(
            ProxyConfig(
                enabled=True,
                type="http",
                host="nv.example",
                port=1,
                state="NV",
                pool=[
                    {
                        "state": "TX",
                        "host": "tx.example",
                        "port": 2,
                        "username": "u",
                        "password": "p",
                    }
                ],
            )
        )
        res = await _observe(wm, cfg, geo_state="TX")
        assert res.success, res.error
        assert seen["proxy_url"] == "http://u:p@tx.example:2"

    @pytest.mark.asyncio
    async def test_no_state_claim_needs_no_state_exit(self, wm, monkeypatch) -> None:
        """Observing without geo_state is a weaker claim, and always allowed."""
        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        res = await _observe(wm, _Cfg(ProxyConfig(enabled=False)))
        assert res.success, res.error
        assert res.data["geo_state"] == "n/a" and res.data["proxied"] is False
        rows = await wm.list_evidence("c1")
        assert rows and all(r.geo_state == "n/a" for r in rows)


class TestAnalyzeHasTheSameRule:
    @pytest.mark.asyncio
    async def test_analyze_refuses_an_unroutable_state_before_reading_anything(
        self, wm, monkeypatch
    ) -> None:
        from tools.watch.tools import WatchAnalyzeTool

        await _seed(wm)
        seen: dict[str, Any] = {}
        _fake_pages(monkeypatch, seen)
        t = WatchAnalyzeTool()
        t._watch_manager = wm
        t._router = _Router()
        t._config = _Cfg(ProxyConfig(enabled=False))
        res = await t.execute(
            {"subject": "Rival", "company_id": "c1", "geo_state": "NV", "save": False}
        )
        assert not res.success
        assert "No network exit for geo_state=NV" in res.error
        assert "proxy_url" not in seen


class TestConfigLoadsTheState:
    def test_state_is_read_and_uppercased(self, tmp_path) -> None:
        import yaml

        from core.config import load_config

        path = tmp_path / "c.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "proxy": {
                        "enabled": True,
                        "type": "http",
                        "host": "h",
                        "port": 1,
                        "state": "nv",
                    },
                }
            )
        )
        assert load_config(path).proxy.state == "NV"

    def test_missing_state_is_empty(self, tmp_path) -> None:
        import yaml

        from core.config import load_config

        path = tmp_path / "c.yaml"
        path.write_text(yaml.safe_dump({"proxy": {"enabled": False}}))
        assert load_config(path).proxy.state == ""


class TestTheAgentIsToldWhatTheProxyCovers:
    def test_runtime_state_names_the_scope_when_on(self) -> None:
        from core.runtime_state import build_runtime_state

        xml = build_runtime_state(
            network={
                "proxy": True,
                "exit": "geo.example:12321",
                "state": "NV",
                "scope": ["browser"],
            },
        )
        assert '<network proxy="on" exit="geo.example:12321" state="NV" scope="browser">' in xml
        assert "shell/curl" in xml and "proves nothing" in xml
        assert "do not loop over checkers" in xml

    def test_runtime_state_says_off_when_off(self) -> None:
        from core.runtime_state import build_runtime_state

        assert '<network proxy="off"/>' in build_runtime_state(network={"proxy": False})

    def test_runtime_state_omits_it_when_unknown(self) -> None:
        from core.runtime_state import build_runtime_state

        assert "<network" not in build_runtime_state()
