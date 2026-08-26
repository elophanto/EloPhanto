"""Logged-in observation (docs/88): the agent signs in itself, and the
verdict is read from the page — never assumed."""

from __future__ import annotations

import json

import pytest

from core.watch_login import (
    click_anti_bot_checkbox,
    login_to_site,
    open_login_form,
    session_state,
)


class _Browser:
    """The bridge contract, minus Chrome. Pages are dicts of what the DOM
    would answer; browser_click_text RAISES on a miss, as the real one does."""

    def __init__(self, *, pages: dict, start: str, widget: dict | None = None) -> None:
        self.pages = pages
        self.url = start
        self.calls: list[tuple[str, dict]] = []
        self.typed: list[str] = []
        self.widget = widget or {"kind": "", "box": None, "token": False, "challenge": False}
        self.clicks: list[tuple[float, float]] = []

    @property
    def page(self) -> dict:
        return self.pages.get(self.url, {})

    async def call_tool(self, name: str, params: dict):
        self.calls.append((name, params))
        if name == "browser_navigate":
            self.url = params["url"]
            return {"success": True}
        if name == "browser_wait":
            return {"success": True}
        if name == "browser_capture":
            return {"success": True}
        if name == "browser_extract":
            return {"success": True, "text": self.page.get("text", "")}
        if name == "browser_press_key":
            if self.page.get("submits_on_enter"):
                self.url = self.page.get("after_submit", self.url)
            return {"success": True}
        if name == "browser_type_text":
            self.typed.append(params["text"])
            if self.page.get("submits_on_enter") and params.get("pressEnter"):
                self.url = self.page.get("after_submit", self.url)
            return {"success": True}
        if name == "browser_click_at":
            self.clicks.append((params["x"], params["y"]))
            self.widget = {**self.widget, "token": True, "challenge": False}
            return {"success": True}
        if name == "browser_click_text":
            for label in self.page.get("clickable", []):
                if params["text"].lower() in label.lower():
                    self.url = self.page.get("click_to", {}).get(label, self.url)
                    return {"success": True, "matchedText": label}
            raise RuntimeError(f'No element matching text: "{params["text"]}"')
        if name == "browser_eval":
            expr = params["expression"]
            if "location.href" in expr:
                return {"success": True, "resultJson": json.dumps(self.url)}
            if "input[type=password]" in expr and "length" in expr:
                return {"success": True, "resultJson": json.dumps(1 if self.page.get("password") else 0)}
            if "out.kind" in expr or "g-recaptcha-response" in expr:
                return {"success": True, "resultJson": json.dumps(json.dumps(self.widget))}
            if "closest('form')" in expr:  # the form's own submit button
                if not self.page.get("password"):
                    return {"success": True, "resultJson": json.dumps("no-password")}
                if self.page.get("submit_disabled"):
                    return {"success": True, "resultJson": json.dumps("disabled")}
                target = (self.page.get("click_to") or {}).get("Log In")
                if target:
                    self.url = target
                    return {"success": True, "resultJson": json.dumps("clicked:Log In")}
                return {"success": True, "resultJson": json.dumps("no-button")}
            return {"success": True, "resultJson": json.dumps("ok")}
        return {"success": True}


LOGGED_OUT = {"text": "Log in or create account to play", "clickable": ["Log In"], "password": False}
FORM = {"text": "Login now", "password": True, "clickable": ["Log In"],
        "click_to": {"Log In": "https://b.example/lobby"},
        "submits_on_enter": True, "after_submit": "https://b.example/lobby"}
LOBBY = {"text": "My account · Log out · Buy coins · sweeps coins balance", "password": False, "clickable": []}


class TestSessionVerdict:
    @pytest.mark.asyncio
    async def test_logged_in_is_read_from_the_page_not_assumed(self) -> None:
        b = _Browser(pages={"https://b.example/": LOBBY}, start="https://b.example/")
        state, hits_in, _ = await session_state(b)
        assert state == "logged_in" and "log out" in hits_in

        b2 = _Browser(pages={"https://b.example/": LOGGED_OUT}, start="https://b.example/")
        state2, _, hits_out = await session_state(b2)
        assert state2 == "logged_out" and hits_out


class TestFormDiscovery:
    @pytest.mark.asyncio
    async def test_direct_login_path_is_preferred(self) -> None:
        b = _Browser(
            pages={"https://b.example": LOGGED_OUT, "https://b.example/login": FORM},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")
        assert note == "form at /login" and b.url == "https://b.example/login"

    @pytest.mark.asyncio
    async def test_a_missing_label_does_not_kill_the_flow(self) -> None:
        """browser_click_text raises on a miss (Chumba, 2026-08-26)."""
        b = _Browser(
            pages={"https://b.example": {"text": "welcome", "password": False, "clickable": []}},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")  # must not raise
        assert note == "no form found"


class TestAntiBot:
    @pytest.mark.asyncio
    async def test_checkbox_is_clicked_like_any_control(self) -> None:
        b = _Browser(pages={"u": {}}, start="u",
                     widget={"kind": "recaptcha", "box": {"x": 100, "y": 200, "w": 300, "h": 74},
                             "token": False, "challenge": False})
        assert await click_anti_bot_checkbox(b) == "passed"
        x, y = b.clicks[0]
        assert 100 < x < 160 and y == pytest.approx(237, abs=2)

    @pytest.mark.asyncio
    async def test_a_puzzle_is_reported_never_solved(self) -> None:
        class _Puzzle(_Browser):
            async def call_tool(self, name, params):
                if name == "browser_click_at":
                    self.clicks.append((params["x"], params["y"]))
                    self.widget = {**self.widget, "challenge": True}  # escalates
                    return {"success": True}
                return await super().call_tool(name, params)

        b = _Puzzle(pages={"u": {}}, start="u",
                    widget={"kind": "recaptcha", "box": {"x": 0, "y": 0, "w": 300, "h": 74},
                            "token": False, "challenge": False})
        assert await click_anti_bot_checkbox(b) == "challenge"
        assert not b.widget.get("token")

    @pytest.mark.asyncio
    async def test_no_widget_is_not_a_captcha(self) -> None:
        b = _Browser(pages={"u": {}}, start="u")
        assert await click_anti_bot_checkbox(b) == "none"


class TestSubmitIsFormScoped:
    @pytest.mark.asyncio
    async def test_the_header_login_link_is_not_the_submit_button(self) -> None:
        """Clicking visible text "Log In" hits the header link and abandons
        the filled form (Card Crush, Hello Millions, 2026-08-26)."""
        from core.watch_login import submit_login_form

        page = {"text": "login", "password": True,
                "clickable": ["Log In"], "click_to": {"Log In": "https://b.example/lobby"}}
        b = _Browser(pages={"https://b.example/login": page}, start="https://b.example/login")
        note = await submit_login_form(b)
        assert note == "submitted via 'Log In'" and b.url == "https://b.example/lobby"
        # it used the scoped JS, never a text click
        assert not [c for c in b.calls if c[0] == "browser_click_text"]

    @pytest.mark.asyncio
    async def test_a_disabled_button_is_reported_not_forced(self) -> None:
        from core.watch_login import submit_login_form

        page = {"text": "login", "password": True, "submit_disabled": True}
        b = _Browser(pages={"u": page}, start="u")
        assert "disabled" in await submit_login_form(b)


class TestLoginToSite:
    @pytest.mark.asyncio
    async def test_end_to_end_verdict_and_credentials_used(self) -> None:
        b = _Browser(
            pages={"https://b.example": LOGGED_OUT, "https://b.example/login": FORM,
                   "https://b.example/lobby": LOBBY},
            start="https://b.example",
        )
        res = await login_to_site(
            b, {"brand": "B", "url": "https://b.example", "username": "u@e.com", "password": "pw"}
        )
        assert res["verdict"] == "logged_in" and "form at /login" in res["note"]
        assert b.typed[:2] == ["u@e.com", "pw"]

    @pytest.mark.asyncio
    async def test_a_failed_login_is_never_reported_as_a_session(self) -> None:
        stuck = {**FORM, "submits_on_enter": False, "click_to": {}}  # submit does nothing
        b = _Browser(
            pages={"https://b.example": LOGGED_OUT, "https://b.example/login": stuck},
            start="https://b.example",
        )
        res = await login_to_site(
            b, {"brand": "B", "url": "https://b.example", "username": "u", "password": "bad"}
        )
        assert res["verdict"] == "logged_out"

    @pytest.mark.asyncio
    async def test_an_existing_session_is_recognised_without_typing(self) -> None:
        b = _Browser(pages={"https://b.example": LOBBY}, start="https://b.example")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example",
                                      "username": "u", "password": "pw"})
        assert res["verdict"] == "already_logged_in" and b.typed == []
