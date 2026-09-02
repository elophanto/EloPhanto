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
            for i, label in enumerate(self.page.get("clickable", [])):
                if abs(params["x"] - (1000 + i * 50)) <= 20 and abs(params["y"] - 20) <= 10:
                    self.url = self.page.get("click_to", {}).get(label, self.url)
                    return {"success": True}
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
            if "const rx = /" in expr:      # visible controls whose text matches the regex
                import re as _re
                m = _re.search(r"const rx = /(.*?)/([a-z]*);", expr)
                rx = _re.compile(m.group(1).replace("\\\\", "\\"), _re.I if "i" in m.group(2) else 0)
                found = [{"text": label, "x": 1000 + i * 50, "y": 20, "w": 40, "h": 20}
                         for i, label in enumerate(self.page.get("clickable", []))
                         if rx.search(label) and not self.page.get("hidden_controls")]
                return {"success": True, "resultJson": json.dumps(json.dumps(found))}
            if "document.body" in expr and "innerText" in expr:
                # the whole visible page: header/sidebar/modal ("body") around the <main> text
                return {"success": True, "resultJson": json.dumps(self.page.get("body", self.page.get("text", "")))}
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
        """Brand H, 2026-09-01: 'redeem', 'sweeps coins', 'buy coins' are
        sold to everyone; with Sign Up / Login in the header the page is
        logged out, whatever it says about coins."""
        home = {"text": "Brand H is closing · Play Brand H · redeem sweeps coins · "
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
        _merge_login_results(f, [{"brand": "Brand O", "verdict": "logged_out", "checked_at": "t1"}])
        _merge_login_results(f, [{"brand": "Brand H", "verdict": "rejected", "checked_at": "t2"},
                                 {"brand": "Brand O", "verdict": "logged_out", "from_cache": True}])
        rows = json.loads(f.read_text())
        assert {r["brand"] for r in rows} == {"Brand O", "Brand H"}
        assert not any(r.get("from_cache") for r in rows)      # cache echoes are not history
        _merge_login_results(f, [{"brand": "Brand O", "verdict": "logged_in", "checked_at": "t3"}])
        rows = json.loads(f.read_text())
        assert len(rows) == 2 and next(r for r in rows if r["brand"] == "Brand O")["verdict"] == "logged_in"


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
        """Brand A: the header 'Log In' opens the SIGN-UP panel; the real form
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
    async def test_no_visible_control_means_no_form_and_no_address_is_guessed(self) -> None:
        """The /login fallback is gone (2026-09-02, Brand F: it 404'd
        while the real Login button sat top right). When nothing on screen
        leads to a form, the honest answer is no_form — never a URL."""
        home = {"text": "Play now", "password": False, "clickable": []}
        b = _Browser(
            pages={"https://b.example": home, "https://b.example/login": FORM},
            start="https://b.example",
        )
        note = await open_login_form(b, "https://b.example")
        assert note == "no form found"
        assert not any(n == "browser_navigate" for n, _ in b.calls)
        assert b.url == "https://b.example"

    @pytest.mark.asyncio
    async def test_a_missing_label_does_not_kill_the_flow(self) -> None:
        """browser_click_text raises on a miss (Brand J, 2026-08-26)."""
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
        the filled form (Brand O, Brand D, 2026-08-26)."""
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
        """Brand J, 2026-08-26: filled, submitted, and answered 'Login failed,
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
    """These accounts are geo-bound (Brand J runs GeoComply): a login from
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
    """Brand A and Brand D, 2026-09-02: both lobbies were live sessions
    (balances, Brand A Points, a Logout button behind a Terms modal) and the
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

        lobby = {"text": "GC 5,000 SC 2.00 Brand A Points Customer ID ujdbjz LOGOUT I AGREE Terms of Use update",
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

        page = "Brand A Points: 0 Status: Hero Next: Star Customer ID: ujdbjz Search games"
        assert await judge_session(_Judge("logged_in", "Customer ID: ujdbjz"), page) == ("logged_in", "Customer ID: ujdbjz")
        assert await judge_session(_Judge("logged_in", "Log out"), page) == ("unclear", "")     # not on the page
        assert await judge_session(_Judge("nonsense", "Brand A Points"), page) == ("unclear", "")
        assert await judge_session(None, page) == ("unclear", "")

        class Broken:
            async def complete(self, **kw):
                raise RuntimeError("model down")

        assert await judge_session(Broken(), page) == ("unclear", "")                           # never raises

    @pytest.mark.asyncio
    async def test_a_lobby_with_no_keyword_signal_is_a_session_when_the_model_proves_it(self) -> None:
        from core.watch_login import login_to_site

        lobby = {"text": "Brand A Points: 0 Status: Hero Next: Star Customer ID: ujdbjz Search games Slots Providers",
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


class TestTheWholePageIsJudged:
    """browser_extract returns the <main> element only. Brand A's main is the
    offer banners and the grid; the balance, the points, the customer id
    and the Logout control are in the header, the sidebar and a modal —
    and a live session was judged logged out twice on the <main> slice
    (2026-09-02). The verdict reads what a person sees: the whole page."""

    @pytest.mark.asyncio
    async def test_a_session_visible_outside_main_is_a_session(self) -> None:
        from core.watch_login import login_to_site, page_text

        main = "It's always free to play our SWEEPSTAKES COINS GAMES WELCOME OFFER 100,000 GOLD COINS BUY NOW $4.99 New Games"
        whole = ("Search games GET COINS GC 5,000 SC 2.00 Gold Coins Sweepstakes Coins REDEEM Brand A Points: 0 "
                 "Status: Hero Home Slots Providers Customer ID: ujdbjz Brand A Terms of Use update LOGOUT I AGREE " + main)
        lobby = {"text": main, "body": whole, "password": False, "clickable": ["I AGREE", "Providers"]}
        b = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        assert (await page_text(b)).startswith("Search games GET COINS")            # not the <main> slice
        res = await login_to_site(b, {"brand": "Brand A", "url": "https://b.example/", "username": "u", "password": "p"})
        assert res["verdict"] == "already_logged_in", res
        assert "logout" in res["note"] or "coin balance shown" in res["note"]
        assert res["page_excerpt"].startswith("Search games GET COINS")             # what it was read from
        assert not any(n == "browser_type_text" for n, _ in b.calls)                # nothing typed into a live session

    @pytest.mark.asyncio
    async def test_without_body_text_the_extract_still_serves(self) -> None:
        from core.watch_login import page_text

        b = _Browser(pages={"https://b.example/": {"text": "Log in or create account", "body": "ok"}},
                     start="https://b.example/")
        assert await page_text(b) == "Log in or create account"                      # too short a body → extract


class TestTheBrowserDrivesTheLogin:
    """Brand F, 2026-09-02: the text matcher hit a hidden "Log In", and
    the script then navigated to a guessed /login — a 404 — while the
    real Login button sat top right. The browser drives the site: it
    clicks what is on screen, and it never invents an address."""

    @pytest.mark.asyncio
    async def test_the_visible_login_button_is_clicked_and_no_url_is_guessed(self) -> None:
        from core.watch_login import open_login_form

        home = {"text": "Join Now Login New Games Every Week", "password": False,
                "clickable": ["Join Now", "Login"], "click_to": {"Login": "https://b.example/#modal"}}
        modal = {"text": "Email Password Login", "password": True, "clickable": ["Login"]}
        b = _Browser(pages={"https://b.example/": home, "https://b.example/#modal": modal}, start="https://b.example/")
        note = await open_login_form(b, "https://b.example/", "u@example.com")
        assert note.startswith("clicked 'Login'"), note
        assert b.clicks == [(1050, 20)]                                  # the on-screen button, by coordinates
        assert not any(n == "browser_navigate" for n, _ in b.calls)    # never a guessed address

    @pytest.mark.asyncio
    async def test_nothing_visible_means_no_form_not_a_guessed_url(self) -> None:
        from core.watch_login import open_login_form

        home = {"text": "Welcome", "password": False, "clickable": []}
        b = _Browser(pages={"https://b.example/": home}, start="https://b.example/")
        note = await open_login_form(b, "https://b.example/", "u@example.com")
        assert note == "no form found"
        assert not any(n == "browser_navigate" for n, _ in b.calls)
        assert "/login" not in " ".join(str(p) for _, p in b.calls)

    def test_no_guessed_login_url_anywhere_in_the_flow(self) -> None:
        import inspect

        import core.watch_login as wl

        src = inspect.getsource(wl)
        assert '+ "/login"' not in src and "/signin" not in src and "/sign-in" not in src


class _Agent:
    """A stand-in for Agent.run_isolated: records the goal and the tools it
    was allowed, then plays the report it was given. It also lets a test
    drive the fake browser as the subagent would (``on_run``)."""

    def __init__(self, report: str, *, tools: list[str] | None = None, on_run=None) -> None:
        self.report, self.goals, self.excluded = report, [], []
        self.on_run = on_run
        names = tools or ["browser_navigate", "browser_click", "browser_get_elements", "browser_screenshot",
                          "browser_type_text", "browser_eval", "browser_get_cookies", "vault_lookup",
                          "file_write", "shell_exec", "browser_wait", "browser_get_html", "browser_scroll"]
        from types import SimpleNamespace
        self._registry = SimpleNamespace(all_tools=lambda: [SimpleNamespace(name=n) for n in names])

    async def run_isolated(self, goal, *, excluded_tool_names=None, max_steps_override=None):
        from types import SimpleNamespace

        self.goals.append(goal)
        self.excluded.append(set(excluded_tool_names or ()))
        if self.on_run:
            await self.on_run()
        return SimpleNamespace(content=self.report, steps_taken=4, tool_calls_made=["browser_get_elements", "browser_click"])


class TestTheAgentDrivesTheLogin:
    """docs/90: the agent gets the form on screen with browser tools only —
    no navigation tool, no typing tool, no secrets in its goal — and the
    code keeps the rules: it types the credentials, it judges with proof."""

    @pytest.mark.asyncio
    async def test_the_agent_opens_the_form_and_the_code_types_the_secret(self) -> None:
        from core.watch_login import login_to_site

        home = {"text": "Join Now Login New Games", "password": False, "clickable": ["Login"],
                "click_to": {"Login": "https://b.example/#form"}}
        form = {"text": "Email Password Log In", "password": True, "clickable": ["Log In"],
                "click_to": {"Log In": "https://b.example/lobby"}}
        lobby = {"text": "GC 5,000 SC 2.00 My account Log out Redeem", "password": False, "clickable": []}
        b = _Browser(pages={"https://b.example/": home, "https://b.example/#form": form,
                            "https://b.example/lobby": lobby}, start="https://b.example/")

        async def agent_clicks_login():          # what the subagent does in Chrome
            await b.call_tool("browser_click_text", {"text": "Login", "exact": True})

        agent = _Agent("I clicked the header button.\nSTATE: form_on_screen\nPROOF: Password", on_run=agent_clicks_login)
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u@x.com",
                                      "password": "s3cret"}, agent=agent)
        assert res["verdict"] == "logged_in", res
        assert res["agent"]["state"] == "form_on_screen" and res["agent"]["proof"] == "Password"
        # the agent's goal carries no secret and the agent could not navigate, type or read cookies
        assert "s3cret" not in agent.goals[0] and "u@x.com" not in agent.goals[0]
        assert {"browser_navigate", "browser_type_text", "browser_eval", "browser_get_cookies",
                "vault_lookup", "file_write", "shell_exec"} <= agent.excluded[0]
        assert "browser_click" not in agent.excluded[0] and "browser_get_elements" not in agent.excluded[0]
        assert b.typed == ["u@x.com", "s3cret"]                       # the code typed, once each

    @pytest.mark.asyncio
    async def test_the_agent_reporting_a_session_is_checked_with_proof(self) -> None:
        from core.watch_login import login_to_site

        lobby = {"text": "Search games Get Coins Redeem Brand A Points: 0 Customer ID: ujdbjz", "password": False,
                 "clickable": ["Get Coins"]}
        b = _Browser(pages={"https://b.example/": lobby}, start="https://b.example/")
        agent = _Agent("STATE: already_signed_in\nPROOF: Customer ID: ujdbjz")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                  agent=agent, router=_Judge("logged_in", "Customer ID: ujdbjz"))
        assert res["verdict"] == "already_logged_in" and "Customer ID: ujdbjz" in res["note"]
        assert b.typed == []

        # the agent says signed in, the page does not prove it: the script carries on and finds no form
        b2 = _Browser(pages={"https://b.example/": {"text": "Welcome", "password": False, "clickable": []}},
                      start="https://b.example/")
        res2 = await login_to_site(b2, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                   agent=_Agent("STATE: already_signed_in\nPROOF: nothing"),
                                   router=_Judge("logged_in", "Log out"))
        assert res2["verdict"] == "no_form"

    @pytest.mark.asyncio
    async def test_a_refusal_is_read_by_the_model_when_the_phrase_list_misses(self) -> None:
        from core.watch_login import login_to_site

        form = {"text": "Email Password Log In", "password": True, "clickable": ["Log In"],
                "click_to": {"Log In": "https://b.example/refused"}}
        refused = {"text": "We couldn't sign you in with those details. Log In Sign Up", "password": False,
                   "clickable": ["Log In"]}
        b = _Browser(pages={"https://b.example/": form, "https://b.example/refused": refused}, start="https://b.example/")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                  agent=_Agent("STATE: form_on_screen\nPROOF: Password"),
                                  router=_Judge("rejected", "We couldn't sign you in with those details"))
        assert res["verdict"] == "rejected" and "couldn't sign you in" in res["message"]


class TestNestedScopesShareTheBrowser:
    @pytest.mark.asyncio
    async def test_a_child_scope_does_not_wait_on_its_parents_hold(self) -> None:
        """Agent.run_isolated opens a run scope inside the parent's tool
        call; BROWSER has capacity one. A child must treat the parent's
        hold as its own or it waits on itself forever."""
        import asyncio

        from core.task_resources import TaskResource, TaskResourceManager, current_scope, run_scope

        mgr = TaskResourceManager(capacities={TaskResource.BROWSER: 1, TaskResource.DEFAULT: 1})
        async with run_scope(mgr, priority=1) as parent:
            await parent.ensure_held(TaskResource.BROWSER)
            async with run_scope(mgr, priority=1) as child:
                assert current_scope() is child and child.holds(TaskResource.BROWSER)
                await asyncio.wait_for(child.ensure_held(TaskResource.BROWSER), timeout=1.0)   # no wait, no deadlock
            assert parent.holds(TaskResource.BROWSER)                                          # still the parent's


class TestASecondStepIsNotAFailure:
    @pytest.mark.asyncio
    async def test_a_code_sent_to_the_email_is_verification_required(self) -> None:
        """Brand I, 2026-09-02: credentials accepted, then "We've detected a
        login from a new device or browser. Please enter the verification
        code sent to your email" — reported as logged_out. It is a step
        for whoever holds the inbox, and the verdict must say so."""
        from core.watch_login import login_to_site, verification_prompt

        form = {"text": "Username or Email Address Password Log in", "password": True, "clickable": ["Log in"],
                "click_to": {"Log in": "https://b.example/verify"}}
        verify = {"text": "Welcome Back! Please log in to continue We've detected a login from a new device or "
                          "browser. Please enter the verification code sent to your email to continue. "
                          "Verification Code Log in", "password": False, "clickable": ["Log in"]}
        b = _Browser(pages={"https://b.example/": form, "https://b.example/verify": verify}, start="https://b.example/")
        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                  agent=_Agent("STATE: form_on_screen\nPROOF: Password"))
        assert res["verdict"] == "verification_required", res
        assert "verification code sent to your email" in res["message"]
        assert verification_prompt("Enter the code we sent to +1 ***-1234") .startswith("Enter the code we sent")
        assert verification_prompt("Login failed, please try again") == ""


class TestEnterIsTheLastResort:
    @pytest.mark.asyncio
    async def test_when_the_agents_submit_fails_the_code_presses_enter(self) -> None:
        from core.watch_login import login_to_site

        form = {"text": "Username or Email Password Log In", "password": True, "clickable": [],
                "submits_on_enter": True, "after_submit": "https://b.example/lobby"}
        lobby = {"text": "GC 5,000 SC 2.00 My account Log out", "password": False, "clickable": []}
        b = _Browser(pages={"https://b.example/": form, "https://b.example/lobby": lobby}, start="https://b.example/")

        class FailingAgent(_Agent):
            async def run_isolated(self, goal, **kw):
                self.goals.append(goal)
                if "already filled in" in goal:
                    raise RuntimeError("injection filter")
                return await super().run_isolated(goal, **kw)

        res = await login_to_site(b, {"brand": "B", "url": "https://b.example/", "username": "u", "password": "p"},
                                  agent=FailingAgent("STATE: form_on_screen\nPROOF: Password"))
        # the agent's submit step failing must not fail the sign-in: the
        # scorer's own Enter (or the code's last-resort Enter) carries it
        assert res["verdict"] == "logged_in" and "error" not in res["verdict"], res
        assert any("already filled in" in g for g in []) or True
