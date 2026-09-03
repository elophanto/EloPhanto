"""The general web_search / web_extract tools speak the dated Search.sh
contract: date controls on the request, dates on every source and page,
and the engine's conflicts passed through for the agent to weigh."""

from __future__ import annotations

from typing import Any

import pytest


class _Resp:
    def __init__(self, data: dict[str, Any], code: int = 200):
        self._data, self.status_code, self.text = data, code, ""

    def json(self) -> dict[str, Any]:
        return self._data


def _client(calls: list[dict[str, Any]], data: dict[str, Any]):
    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, *, json, headers):
            calls.append({"url": url, "body": json})
            return _Resp(data)

    return _Client


class TestWebSearchDates:
    @pytest.mark.asyncio
    async def test_date_controls_go_out_and_dates_and_conflicts_come_back(self, monkeypatch) -> None:
        import httpx

        from tools.data.web_search import WebSearchTool

        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(httpx, "AsyncClient", _client(calls, {
            "answer": "…",
            "confidence": 0.8,
            "sources": [{"title": "n", "url": "https://n.example/", "snippet": "s",
                         "published_at": "2026-07-14T08:00:00.000Z", "modified_at": None,
                         "date_confidence": "high", "date_sources": {"published_at": "article:published_time"}}],
            "citations": [{"claim": "left", "source_url": "https://n.example/", "verified": True,
                           "source_date": "2026-07-14T08:00:00.000Z",
                           "conflict": {"with_url": "https://o.example/", "relation": "newer"}}],
            "conflicts": [{"summary": "sources disagree", "dated": True,
                           "newer": {"claim": "left", "source_url": "https://n.example/", "date": "2026-07-14"},
                           "older": {"claim": "carried", "source_url": "https://o.example/", "date": "2024-03-02"}}],
            "metadata": {"duration_ms": 1200, "conflict_count": 1},
        }))
        t = WebSearchTool()
        t._vault = {"search_sh_api_key": "sk-test"}
        res = await t.execute({"query": "q", "since": "2026-03-01", "recency": "past_year", "freshness_boost": True})
        assert res.success, res.error
        body = calls[0]["body"]
        assert body["since"] == "2026-03-01" and body["recency"] == "past_year" and body["freshness_boost"] is True
        src = res.data["sources"][0]
        assert src["published_at"] == "2026-07-14T08:00:00.000Z" and src["date_confidence"] == "high"
        assert src["date_sources"] == {"published_at": "article:published_time"}
        assert res.data["conflicts"][0]["newer"]["claim"] == "left"
        assert res.data["citations"][0]["conflict"]["relation"] == "newer"
        assert res.data["since"] == "2026-03-01" and res.data["freshness_boost"] is True

    @pytest.mark.asyncio
    async def test_without_controls_nothing_new_is_sent_and_old_engines_still_parse(self, monkeypatch) -> None:
        import httpx

        from tools.data.web_search import WebSearchTool

        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(httpx, "AsyncClient", _client(calls, {
            "answer": "a", "sources": [{"title": "t", "url": "https://x.example/", "snippet": ""}],
        }))
        t = WebSearchTool()
        t._vault = {"search_sh_api_key": "sk-test"}
        res = await t.execute({"query": "q"})
        assert res.success
        assert not {"since", "recency", "freshness_boost"} & set(calls[0]["body"])
        src = res.data["sources"][0]
        assert src["published_at"] is None and src["date_confidence"] is None and src["date_sources"] == {}
        assert res.data["conflicts"] == []

    def test_the_schema_offers_the_controls(self) -> None:
        from tools.data.web_search import WebSearchTool

        props = WebSearchTool().input_schema["properties"]
        assert {"since", "recency", "freshness_boost"} <= set(props)
        assert props["recency"]["enum"] == ["past_day", "past_week", "past_month", "past_year"]


class TestWebExtractDates:
    @pytest.mark.asyncio
    async def test_pages_carry_their_dates_and_archive_marks(self, monkeypatch) -> None:
        import httpx

        from tools.data.web_search import WebExtractTool

        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(httpx, "AsyncClient", _client(calls, {"pages": [
            {"url": "https://a.example/", "title": "A", "content": "text",
             "published_at": None, "modified_at": "2026-02-11T03:14:00.000Z", "date_confidence": "high",
             "date_sources": {"modified_at": "json-ld:dateModified"}, "published_date": "2026-02-11"},
            {"url": "https://gone.example/", "title": "G", "content": "old text",
             "published_at": "2023-01-01", "modified_at": None, "date_confidence": "low",
             "date_sources": {"published_at": "wayback_snapshot"}, "via": "wayback", "snapshot_date": "2023-01-01"},
        ]}))
        t = WebExtractTool()
        t._vault = {"search_sh_api_key": "sk-test"}
        res = await t.execute({"urls": ["https://a.example/", "https://gone.example/"]})
        assert res.success, res.error
        a, g = res.data["pages"]
        assert a["modified_at"] == "2026-02-11T03:14:00.000Z" and a["date_confidence"] == "high"
        assert "via" not in a
        assert g["via"] == "wayback" and g["snapshot_date"] == "2023-01-01"
        assert res.data["count"] == 2
