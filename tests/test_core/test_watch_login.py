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
            if expr.startswith("[...document.querySelectorAll('input[type=password]')]"):
                return {"success": True, "resultJson": json.dumps(1 if self.page.get("password") else 0)}
            if "out.kind" in expr or "g-recaptcha-response" in expr:
                return {"success": True, "resultJson": json.dumps(json.dumps(self.widget))}
            if "no-password" in expr:  # the form's own submit button
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

    @pytest.mark.asyncio
    async def test_coins_talk_on_a_logged_out_homepage_is_not_a_session(self) -> None:
        """LuckyLand, 2026-09-01: 'redeem', 'sweeps coins', 'buy coins' are
        sold to everyone; with Sign Up / Login in the header the page is
        logged out, whatever it says about coins."""
        home = {"text": "LuckyLand Slots is closing · Play LuckyLand Casino · redeem sweeps coins · "
                        "buy coins · Sign up · Login", "password": False, "clickable": ["Login"]}
        b = _Browser(pages={"https://b.example/": home}, start="https://b.example/")
        state, hits_in, hits_out = await session_state(b)
        assert state == "logged_out" and "login" in hits_out and "redeem" in hits_in

        coins_only = {"text": "Buy coins · redeem · sweeps coins", "password": False, "clickable": []}
        b2 = _Browser(pages={"https://b.example/": coins_only}, start="https://b.example/")
        assert (await session_state(b2))[0] == "unclear"        # no control either way: say so

    def test_login_results_merge_across_calls(self, tmp_path) -> None:
        """The agent signs in one brand per call; the cooldown reads the file,
        so a call must not erase the previous brand's verdict."""
        import json

        from tools.watch.tools import _merge_login_results

        f = tmp_path / "results.json"
        _merge_login_results(f, [{"brand": "Card Crush", "verdict": "logged_out", "checked_at": "t1"}])
        _merge_login_results(f, [{"brand": "LuckyLand Slots", "verdict": "rejected", "checked_at": "t2"},
                                 {"brand": "Card Crush", "verdict": "logged_out", "from_cache": True}])
        rows = json.loads(f.read_text())
        assert {r["brand"] for r in rows} == {"Card Crush", "LuckyLand Slots"}
        assert not any(r.get("from_cache") for r in rows)      # cache echoes are not history
        _merge_login_results(f, [{"brand": "Card Crush", "verdict": "logged_in", "checked_at": "t3"}])
        rows = json.loads(f.read_text())
        assert len(rows) == 2 and next(r for r in rows if r["brand"] == "Card Crush")["verdict"] == "logged_in"


class TestFormDiscovery:
    """A person clicks the login control; they do not guess URLs."""

    @pytest.mark.asyncio
    async def test_the_visible_control_is_clicked_not_a_url_guessed(self) -> None:
        home = {"text": "Play now", "password": False, "clickable": ["Log In"],
                "click_to": {"Log In": "https://b.example/#login"}}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/#login": FORM},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")
        assert "clicked 'Log In'" in note
        assert not [c for c in b.calls if c[0] == "browser_navigate"]  # no URL guessing

    @pytest.mark.asyncio
    async def test_a_signup_panel_is_switched_to_login(self) -> None:
        """Pulsz: the header 'Log In' opens the SIGN-UP panel; the real form
        is behind 'Already got an account? Log in >'."""
        home = {"text": "Play now", "password": False, "clickable": ["Log In"],
                "click_to": {"Log In": "https://b.example/register"}}
        signup = {"text": "Sign up with email. Already got an account? Log in >",
                  "password": False, "clickable": ["Already got an account? Log in >"],
                  "click_to": {"Already got an account? Log in >": "https://b.example/login"}}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/register": signup,
                   "https://b.example/login": FORM},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")
        assert "clicked 'Log In'" in note and "switched via" in note
        assert b.url == "https://b.example/login"

    @pytest.mark.asyncio
    async def test_login_url_is_the_last_resort_not_the_first(self) -> None:
        home = {"text": "Play now", "password": False, "clickable": []}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/login": FORM},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")
        assert "fell back to /login" in note
        navs = [c[1]["url"] for c in b.calls if c[0] == "browser_navigate"]
        assert navs == ["https://b.example/login"]  # exactly one, and only after clicking failed

    @pytest.mark.asyncio
    async def test_a_missing_label_does_not_kill_the_flow(self) -> None:
        """browser_click_text raises on a miss (Chumba, 2026-08-26)."""
        b = _Browser(
            pages={"https://b.example": {"text": "welcome", "password": False, "clickable": []}},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")  # must not raise
        assert "no form found" in note


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


class TestRejection:
    @pytest.mark.asyncio
    async def test_the_sites_own_rejection_is_reported_verbatim(self) -> None:
        """Chumba, 2026-08-26: filled, submitted, and answered 'Login failed,
        please try again' — an automation report of 'logged_out' would have
        sent someone hunting a bug that was not there."""
        rejected = {"text": "Welcome Back! Login failed, please try again or contact support.",
                    "password": True, "clickable": [], "click_to": {}}
        home = {**LOGGED_OUT, "click_to": {"Log In": "https://b.example/login"}}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/login": rejected},
            start="https://b.example",
        )
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example",
                                      "username": "u", "password": "stale"})
        assert res["verdict"] == "rejected"
        assert "login failed" in res["message"].lower()

    def test_an_ordinary_page_is_not_a_rejection(self) -> None:
        from core.watch_login import login_error

        assert login_error("Play our games and win big prizes today") == ""
        assert "incorrect password" in login_error("Sorry, incorrect password entered").lower()


class TestExitSwitching:
    """These accounts are geo-bound (Chumba runs GeoComply): a login from
    the wrong state can be refused with the right password. The exit is
    proven before any sign-in, never assumed."""

    @pytest.mark.asyncio
    async def test_an_unpromised_state_is_refused_not_faked(self) -> None:
        from types import SimpleNamespace

        from core.watch_login import switch_browser_exit

        cfg = SimpleNamespace(
            request_proxy_url=lambda st: "" if st == "NV" else "http://u:p@x:1",
            exit_for_state=lambda st: None, host="x", port=1, type="http",
            username="u", password="p", bypass=[],
        )
        b = _Browser(pages={"u": {}}, start="u")
        ok, detail = await switch_browser_exit(b, cfg, "NV")
        assert not ok and "no configured exit" in detail["error"]

    @pytest.mark.asyncio
    async def test_no_switch_needed_when_already_on_that_exit(self) -> None:
        from types import SimpleNamespace

        from core.watch_login import switch_browser_exit

        b = _Browser(pages={"u": {}}, start="u")
        b._watch_exit_state = "TX"
        cfg = SimpleNamespace(request_proxy_url=lambda st: "http://u:p@x:1")
        ok, detail = await switch_browser_exit(b, cfg, "TX")
        assert ok and detail["cached"] and not b.calls  # Chrome untouched

    @pytest.mark.asyncio
    async def test_na_is_a_no_op(self) -> None:
        from core.watch_login import switch_browser_exit

        ok, detail = await switch_browser_exit(_Browser(pages={}, start="u"), object(), "n/a")
        assert ok and detail["state"] == "n/a"


class TestCooldown:
    """Repeated sign-in attempts lock accounts — a brand checked recently is
    reported from the stored verdict, not signed into again."""

    def test_a_fresh_result_is_reused_and_a_stale_one_is_not(self, tmp_path) -> None:
        import json as _json
        from datetime import UTC, datetime, timedelta

        from core.watch_login import recent_attempt

        f = tmp_path / "results.json"
        now = datetime.now(UTC)
        f.write_text(_json.dumps([
            {"brand": "Fresh", "verdict": "rejected",
             "checked_at": (now - timedelta(hours=2)).isoformat()},
            {"brand": "Stale", "verdict": "logged_in",
             "checked_at": (now - timedelta(hours=30)).isoformat()},
        ]))
        assert recent_attempt(str(f), "Fresh", within_hours=12)["verdict"] == "rejected"
        assert recent_attempt(str(f), "Stale", within_hours=12) is None
        assert recent_attempt(str(f), "Unknown", within_hours=12) is None
        assert recent_attempt(str(tmp_path / "nope.json"), "Fresh", within_hours=12) is None

    @pytest.mark.asyncio
    async def test_every_attempt_is_stamped_so_the_cooldown_can_work(self) -> None:
        b = _Browser(pages={"https://b.example": LOBBY}, start="https://b.example")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example",
                                      "username": "u", "password": "p"})
        assert res["checked_at"]


class TestLoginToSite:
    @pytest.mark.asyncio
    async def test_end_to_end_verdict_and_credentials_used(self) -> None:
        home = {**LOGGED_OUT, "click_to": {"Log In": "https://b.example/login"}}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/login": FORM,
                   "https://b.example/lobby": LOBBY},
            start="https://b.example",
        )
        res = await login_to_site(
            b, {"brand": "B", "url": "https://b.example", "username": "u@e.com", "password": "pw"}
        )
        assert res["verdict"] == "logged_in" and "clicked 'Log In'" in res["note"]
        assert b.typed[:2] == ["u@e.com", "pw"]

    @pytest.mark.asyncio
    async def test_a_failed_login_is_never_reported_as_a_session(self) -> None:
        stuck = {**FORM, "submits_on_enter": False, "click_to": {}}  # submit does nothing
        home = {**LOGGED_OUT, "click_to": {"Log In": "https://b.example/login"}}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/login": stuck},
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


class TestLiveSessionIsRecognised:
    """Pulsz and Hello Millions, 2026-09-02: both lobbies were live sessions
    (balances, Pulsz Points, a Logout button behind a Terms modal) and the
    check said "no form found" — it judged a spinner, then a click that
    landed on nothing."""

    @pytest.mark.asyncio
    async def test_a_wallet_balance_without_a_login_button_is_a_session(self) -> None:
        lobby = {"text": "GC 15,000 SC 2.50 Get Coins Redeem Loyalty Lounge Recommended Games",
                 "password": False, "clickable": ["Get Coins"]}
        b = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        state, hits_in, _ = await session_state(b)
        assert state == "logged_in" and "coin balance shown" in hits_in

        offer = {"text": "Get 15,000 GC + 2.5 SC free on sign up · Log In · Sign Up", "password": False,
                 "clickable": ["Log In"]}
        b2 = _Browser(pages={"https://b.example/": offer}, start="https://b.example/")
        assert (await session_state(b2))[0] == "logged_out"          # an offer, and a Login button

    @pytest.mark.asyncio
    async def test_no_form_on_a_live_lobby_is_already_logged_in(self) -> None:
        from core.watch_login import login_to_site

        lobby = {"text": "GC 5,000 SC 2.00 Pulsz Points Customer ID ujdbjz LOGOUT I AGREE Terms of Use update",
                 "password": False, "clickable": ["I AGREE"]}
        b = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"})
        assert res["verdict"] == "already_logged_in", res


class _Judge:
    """A router whose answer is fixed — the guardrail under test is that a
    verdict only counts when its evidence is printed on the page."""

    def __init__(self, state, evidence):
        self.state, self.evidence, self.calls = state, evidence, 0

    async def complete(self, **kw):
        import json
        from types import SimpleNamespace

        self.calls += 1
        return SimpleNamespace(content=json.dumps({"state": self.state, "evidence": self.evidence, "why": "x"}))


class TestTheAgentJudgesThePage:
    """'The agent would recognise we're already logged in' (Petr,
    2026-09-02). When the keyword check cannot tell, the model reads the
    page — and its verdict counts only with proof printed on the page."""

    @pytest.mark.asyncio
    async def test_a_verdict_needs_printed_proof(self) -> None:
        from core.watch_login import judge_session

        page = "Pulsz Points: 0 Status: Hero Next: Star Customer ID: ujdbjz Search games"
        assert await judge_session(_Judge("logged_in", "Customer ID: ujdbjz"), page) == ("logged_in", "Customer ID: ujdbjz")
        assert await judge_session(_Judge("logged_in", "Log out"), page) == ("unclear", "")     # not on the page
        assert await judge_session(_Judge("nonsense", "Pulsz Points"), page) == ("unclear", "")
        assert await judge_session(None, page) == ("unclear", "")

        class Broken:
            async def complete(self, **kw):
                raise RuntimeError("model down")

        assert await judge_session(Broken(), page) == ("unclear", "")                           # never raises

    @pytest.mark.asyncio
    async def test_a_lobby_with_no_keyword_signal_is_a_session_when_the_model_proves_it(self) -> None:
        from core.watch_login import login_to_site

        lobby = {"text": "Pulsz Points: 0 Status: Hero Next: Star Customer ID: ujdbjz Search games Slots Providers",
                 "password": False, "clickable": ["Providers"]}
        b = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        judge = _Judge("logged_in", "Customer ID: ujdbjz")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                  router=judge)
        assert res["verdict"] == "already_logged_in" and "model: Customer ID: ujdbjz" in res["note"], res
        assert judge.calls == 1

        # the model says logged in but cannot quote the page: the script's own verdict stands
        b2 = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        res2 = await login_to_site(b2, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                   router=_Judge("logged_in", "Log out"))
        assert res2["verdict"] != "already_logged_in"
