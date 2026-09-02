"""Logging the agent's own browser into a tracked brand (docs/88).

The register can hold what a *registered* player sees — ``customer_state``
has always had the vocabulary — but collection only ever ran logged out
because nothing logged in. This does, with the real Chrome the organ
already drives: the brand's own login page, the consent overlay handled
the way the playbook handles it, the credentials the vault holds, the
checkbox anti-bot widget clicked like any other control, and then a
verdict read from the page itself.

Two rules it never bends:

* it clicks a checkbox, it does not solve a puzzle — an image or text
  challenge is reported as ``challenge``, never worked around;
* the verdict comes from what the page shows afterwards, so a failed
  login can never be reported as a session (the same discipline that
  makes ``geo_state`` and ``customer_state`` provable rather than
  assumed).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# What a logged-in session shows, and what a logged-out one still shows.
# Only an account control proves a session: a logged-out homepage sells
# "sweeps coins", "redeem" and "buy coins" to everyone (LuckyLand,
# 2026-09-01: judged "already logged in" on those words while its header
# read Sign Up / Login). The weak words help only when nothing says
# logged-out.
LOGGED_IN_STRONG = (
    "log out", "logout", "sign out", "my account", "account settings", "my profile",
)
LOGGED_IN_WEAK = (
    "gold coins balance", "sweeps coins", "cashier", "redeem", "buy coins",
    "wallet", "vip level", "claim daily", "daily bonus claim",
)
LOGGED_IN_WORDS = LOGGED_IN_STRONG + LOGGED_IN_WEAK
_BALANCE_RE = re.compile(r"\b(?:gc|sc)\s?[\d,]{1,12}(?:\.\d{1,2})?\b", re.I)   # the page text is lower-cased
LOGGED_OUT_WORDS = (
    "log in", "login", "sign in", "create account", "register", "join now",
)
# What a rejected login says. Telling "the credentials are wrong" apart
# from "the automation missed the button" is the whole point of a login
# check (Chumba, 2026-08-26: "Login failed, please try again" — the form
# was filled and submitted correctly, the account simply did not open).
LOGIN_ERROR_PHRASES = (
    "login failed", "incorrect password", "invalid password", "wrong password",
    "incorrect email", "invalid email", "credentials", "do not match",
    "doesn't match", "does not match", "no account", "account not found",
    "please try again", "account is locked", "account has been suspended",
    "too many attempts", "temporarily locked",
)
LOGIN_ENTRY = ("Log In", "Login", "Sign In", "Sign in", "LOG IN", "LOGIN")
SWITCH_TO_LOGIN = (
    "already got an account", "already have an account", "log in",
    "login", "sign in", "existing player",
)
SUBMIT_LABELS = (
    "Log In", "Login", "Sign In", "Continue", "Submit", "LOG IN", "LOGIN NOW",
)

EMAIL_SELECTOR = (
    "input[type=email],"
    "input[name*=email i],input[id*=email i],"
    "input[name*=user i],input[id*=user i],"
    "input[autocomplete=username],input[type=text]"
)
_NOT_EMAIL = "search|promo|code|coupon|zip|phone"


def _val(res: Any) -> Any:
    """browser_eval answers {success, resultJson} — the value JSON-encoded."""
    raw = (res or {}).get("resultJson") if isinstance(res, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw.removesuffix("...[truncated]"))
    except Exception:
        return None


async def _eval(bm: Any, expression: str, max_length: int = 8000) -> Any:
    try:
        return _val(await bm.call_tool("browser_eval", {"expression": expression, "maxLength": max_length}))
    except Exception:
        return None


def _focus_js(which: str) -> str:
    """Focus the visible email or password box, never the site search."""
    if which == "password":
        sel, extra = "input[type=password]", ""
    else:
        sel = EMAIL_SELECTOR
        extra = (
            f"const bad = /{_NOT_EMAIL}/i;"
            "els = els.filter(e => !bad.test((e.name||'') + (e.id||'') + "
            "(e.placeholder||'') + (e.getAttribute('aria-label')||'')));"
        )
    return (
        "(() => {"
        f"let els = [...document.querySelectorAll({sel!r})]"
        ".filter(e => e.offsetParent !== null && !e.disabled && !e.readOnly);"
        f"{extra}"
        "const t = els[0]; if (!t) return 'none';"
        "t.scrollIntoView({block:'center'}); t.focus(); t.click();"
        "return t.name || t.id || t.type;})()"
    )


async def _click_text(bm: Any, text: str, *, exact: bool = True) -> str:
    """Click by visible text, returning what was actually matched ("" for
    nothing). The bridge RAISES when no element matches, and a login flow
    that tries six labels must not die on the first miss (Chumba,
    2026-08-26: BridgeError: No element matching text "Log In")."""
    try:
        res = await bm.call_tool("browser_click_text", {"text": text, "exact": exact})
    except Exception:
        return ""
    return str((res or {}).get("matchedText") or "")


async def has_password_field(bm: Any) -> bool:
    got = await _eval(
        bm,
        "[...document.querySelectorAll('input[type=password]')]"
        ".filter(e => e.offsetParent !== null).length",
    )
    try:
        return int(got or 0) > 0
    except Exception:
        return False


# ── Anti-bot checkbox ──────────────────────────────────────────────────

_WIDGET_JS = (
    "(() => {"
    "const out = {kind: '', box: null, token: false, challenge: false};"
    "const ta = document.querySelector('#g-recaptcha-response,[name=g-recaptcha-response]');"
    "if (ta && ta.value) out.token = true;"
    "for (const f of document.querySelectorAll('iframe')) {"
    "  const src = f.src || '';"
    "  const r = f.getBoundingClientRect();"
    "  if (!r.width || !r.height) continue;"
    "  if (/recaptcha\\/api2\\/anchor|recaptcha\\/enterprise\\/anchor/.test(src)) {"
    "    out.kind = 'recaptcha'; out.box = {x: r.x, y: r.y, w: r.width, h: r.height};"
    "  } else if (/hcaptcha.*checkbox/.test(src)) {"
    "    out.kind = 'hcaptcha'; out.box = {x: r.x, y: r.y, w: r.width, h: r.height};"
    "  } else if (/turnstile/.test(src)) {"
    "    out.kind = 'turnstile'; out.box = {x: r.x, y: r.y, w: r.width, h: r.height};"
    "  } else if (/recaptcha\\/api2\\/bframe|hcaptcha.*challenge/.test(src) && r.width > 200) {"
    "    out.challenge = true;"
    "  }"
    "}"
    "return JSON.stringify(out);})()"
)


async def _widget(bm: Any) -> dict[str, Any]:
    raw = await _eval(bm, _WIDGET_JS)
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


async def click_anti_bot_checkbox(bm: Any, *, rounds: int = 2) -> str:
    """Click a checkbox anti-bot widget ("I'm not a robot") the way a
    person does — a real click at its coordinates, in the real browser.

    Returns ``"none"`` (no widget), ``"passed"`` (token issued),
    ``"challenge"`` (an image/audio puzzle appeared — NOT solved, and never
    will be here) or ``"unresolved"``.
    """
    if bm is None:
        return "none"
    w = await _widget(bm)
    if w.get("token"):
        return "passed"
    if not w.get("kind") or not w.get("box"):
        return "none"
    for _ in range(max(1, rounds)):
        box = w.get("box") or {}
        # The checkbox sits at the left of the anchor frame, vertically centred.
        x = float(box.get("x", 0)) + min(30.0, float(box.get("w", 300)) / 8 + 12)
        y = float(box.get("y", 0)) + float(box.get("h", 74)) / 2
        try:
            await bm.call_tool("browser_click_at", {"x": round(x), "y": round(y)})
        except Exception:
            return "unresolved"
        for _ in range(6):
            await bm.call_tool("browser_wait", {"ms": 1200})
            w = await _widget(bm)
            if w.get("token"):
                return "passed"
            if w.get("challenge"):
                # A puzzle is where this stops: the organ does not defeat
                # anti-bot challenges, it reports them.
                return "challenge"
        if not w.get("box"):
            break
    return "passed" if (await _widget(bm)).get("token") else "unresolved"


# ── The login itself ───────────────────────────────────────────────────


_EMAIL_ONLY_JS = (
    "(() => {"
    "const vis = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null);"
    "if (vis('input[type=password]').length) return 'password';"
    "const bad = /search|promo|code|coupon|zip|phone/i;"
    "const em = vis('input[type=email],input[name*=email i],input[id*=email i]')"
    ".filter(e => !bad.test((e.name||'') + (e.id||'') + (e.placeholder||'')));"
    "return em.length ? 'email-only' : 'none';})()"
)
_NEXT_JS = (
    "(() => {"
    "const words = /(next|continue|proceed|submit|log ?in|sign ?in)/i;"
    "const social = /(google|apple|facebook|twitter|discord)/i;"
    "const b = [...document.querySelectorAll('button,[role=button],input[type=submit],a')]"
    ".filter(e => e.offsetParent !== null && !e.disabled"
    " && !e.closest('header,nav,[class*=header],[class*=navbar]')"
    " && words.test((e.innerText || e.value || '').trim())"
    " && !social.test((e.innerText || e.value || '').trim()))[0];"
    "if (!b) return 'none';"
    "b.scrollIntoView({block:'center'}); b.click();"
    "return (b.innerText || b.value || 'next').trim().slice(0, 18);})()"
)


async def _wait_for_form(bm: Any, seconds: float = 12.0) -> bool:
    """Panels animate, and a login click often NAVIGATES — WOW Vegas takes
    the browser to /login, which needs more than a couple of seconds
    (2026-08-26: reported 'no form' while the form was on its way)."""
    for _ in range(max(1, int(seconds / 1.2))):
        await bm.call_tool("browser_wait", {"ms": 1200})
        if await has_password_field(bm):
            return True
    return False


async def _email_first_step(bm: Any, username: str) -> str:
    """Some brands ask for the e-mail, then the password on the next screen
    (McLuck). Complete the first step so the password field can appear."""
    if not username:
        return ""
    if str(await _eval(bm, _EMAIL_ONLY_JS) or "") != "email-only":
        return ""
    await _eval(bm, _focus_js("email"))
    await bm.call_tool("browser_type_text", {"text": username})
    pressed = str(await _eval(bm, _NEXT_JS) or "none")
    if pressed == "none":
        await bm.call_tool("browser_press_key", {"key": "Enter"})
        pressed = "Enter"
    return f"e-mail step via '{pressed}'" if await _wait_for_form(bm, 8) else ""


async def open_login_form(bm: Any, url: str, username: str = "") -> str:
    """Get a visible password field on screen, the way a person does it:
    click the login control, and when that opens a SIGN-UP panel — as
    several of these brands do — click the "already have an account"
    switch inside it. Only if clicking gets nowhere is ``/login`` tried,
    once, as a fallback. Returns a short note."""
    from core.watch_observe import dismiss_consent

    if await has_password_field(bm):
        return "form already open"
    notes: list[str] = []
    # Clear the consent overlay FIRST: while it is up the login control is
    # not reachable and the click lands on the banner (High 5, 2026-08-26).
    await dismiss_consent(bm)
    for label in LOGIN_ENTRY:
        matched = await _click_text(bm, label)
        if matched and label.lower() in matched.lower():
            notes.append(f"clicked '{matched.strip()[:18]}'")
            break
    if await _wait_for_form(bm, 12):
        return "; ".join(notes) or "form on the page"
    await dismiss_consent(bm)
    step = await _email_first_step(bm, username)
    if step:
        notes.append(step)
        return "; ".join(notes)

    # A sign-up panel: the real login hides behind its switch link.
    for label in SWITCH_TO_LOGIN:
        matched = await _click_text(bm, label, exact=False)
        if not matched or label.split()[0] not in matched.lower():
            continue
        notes.append(f"switched via '{matched.strip()[:22]}'")
        if await _wait_for_form(bm, 10):
            return "; ".join(notes)
        step = await _email_first_step(bm, username)
        if step:
            notes.append(step)
            return "; ".join(notes)
        break

    # Still nothing on screen — ask for the login page itself, once.
    await bm.call_tool("browser_navigate", {"url": url.rstrip("/") + "/login"})
    await bm.call_tool("browser_wait", {"ms": 2500})
    await dismiss_consent(bm)
    if await _wait_for_form(bm, 8):
        notes.append("fell back to /login")
        return "; ".join(notes)
    step = await _email_first_step(bm, username)
    if step:
        notes.append("fell back to /login; " + step)
        return "; ".join(notes)
    return "; ".join(notes + ["no form found"]) if notes else "no form found"


# The form's own submit button. Three traps, all seen live on 2026-08-26:
# the site header's "Log In" link (clicking it abandons the filled form),
# the social buttons — "Continue with Apple/Google/Facebook" — which sit
# right above the fields and match a naive "continue", and forms whose
# button lives outside the password field's wrapper. So: score candidates
# (real login wording and a submit type win, social providers are
# disqualified, below-the-field beats above) and take the best.
_SUBMIT_JS = (
    "(() => {"
    "const pw = [...document.querySelectorAll('input[type=password]')]"
    ".filter(e => e.offsetParent !== null)[0];"
    "if (!pw) return 'no-password';"
    "const strong = /^\\s*(log ?in|sign ?in|log ?in now|submit)/i;"
    "const weak = /(log ?in|sign ?in|continue|submit|enter)/i;"
    "const social = /(google|apple|facebook|twitter|discord|steam|metamask|phone|sms)/i;"
    "const pwTop = pw.getBoundingClientRect().top;"
    "const form = pw.closest('form');"
    "const label = b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim();"
    "let cands = [...document.querySelectorAll("
    "'button,input[type=submit],input[type=button],[role=button],a,"
    "div[class*=btn],div[class*=button],span[class*=btn],span[class*=button]')]"
    ".filter(b => b.offsetParent !== null && !b.disabled"
    " && b.getAttribute('aria-disabled') !== 'true'"
    " && !b.closest('header,nav,[class*=header],[class*=navbar]')"
    " && weak.test(label(b)) && !social.test(label(b))"
    " && !(b.tagName === 'A' && b.getAttribute('href')"
    "      && !/^#|javascript:/.test(b.getAttribute('href'))"
    "      && !/log|sign/i.test(b.getAttribute('href'))));"
    "if (!cands.length) return 'no-button';"
    "const score = b => {"
    "  const t = label(b); let s = 0;"
    "  if (strong.test(t)) s += 4;"
    "  if ((b.type || '') === 'submit') s += 3;"
    "  if (form && form.contains(b)) s += 2;"
    "  const top = b.getBoundingClientRect().top;"
    "  if (top >= pwTop) s += 2;"
    "  return s - Math.abs(top - pwTop) / 1000;"
    "};"
    "cands.sort((a, b) => score(b) - score(a));"
    "const btn = cands[0];"
    "btn.scrollIntoView({block: 'center'}); btn.click();"
    "return 'clicked:' + (label(btn) || 'submit').slice(0, 20);})()"
)


async def submit_login_form(bm: Any) -> str:
    """Press the form's OWN submit button.

    Clicking by visible text is wrong here: nearly every one of these
    sites also has a "Log In" link in the header, and matching that
    navigates away from the half-filled form — which then reads as a
    failed login (Card Crush, Hello Millions, 2026-08-26). Scope the
    search to the element holding the password field.
    """
    got = str(await _eval(bm, _SUBMIT_JS) or "")
    if got.startswith("clicked:") and got[8:].strip():
        return f"submitted via '{got[8:]}'"
    if got == "disabled":
        return "submit disabled (anti-bot or validation)"
    # The JS cannot see into a shadow root, and these apps put the button
    # there (Chumba, 2026-08-26: the visible "LOG IN" exists in no light-DOM
    # query). The bridge's own matcher pierces shadow DOM — use it, then
    # confirm by the form going away rather than by the click's own word.
    for label in ("LOG IN", "Log In", "Login", "LOGIN", "Sign In", "Sign in"):
        matched = await _click_text(bm, label)
        if not matched or "log" not in matched.lower() and "sign" not in matched.lower():
            continue
        await bm.call_tool("browser_wait", {"ms": 2500})
        if not await has_password_field(bm):
            return f"submitted via '{matched.strip()[:18]}'"
    # Last resort: Enter in the password box, which most forms accept.
    await _eval(bm, _focus_js("password"))
    await bm.call_tool("browser_press_key", {"key": "Enter"})
    return "submitted with Enter"


async def fill_and_submit(bm: Any, username: str, password: str) -> str:
    """Type the credentials and submit. Returns a note on what happened."""
    if not await has_password_field(bm):
        return "no password field"
    await _eval(bm, _focus_js("email"))
    await bm.call_tool("browser_type_text", {"text": username})
    await _eval(bm, _focus_js("password"))
    await bm.call_tool("browser_type_text", {"text": password})
    await bm.call_tool("browser_wait", {"ms": 800})
    verdict = await click_anti_bot_checkbox(bm)
    note = "typed credentials" + (f"; captcha {verdict}" if verdict != "none" else "")
    if verdict == "challenge":
        return note
    await bm.call_tool("browser_wait", {"ms": 1200})
    note += "; " + await submit_login_form(bm)
    await bm.call_tool("browser_wait", {"ms": 7000})
    return note


def login_error(text: str) -> str:
    """The site's own rejection message, if it is showing one. This says
    the attempt was REFUSED, not why: "Login failed, please try again"
    covers a stale password, a locked account and a failed anti-bot score
    alike."""
    low = (text or "").lower()
    for phrase in LOGIN_ERROR_PHRASES:
        i = low.find(phrase)
        if i >= 0:
            start = max(0, i - 60)
            return " ".join(text[start : i + 90].split())[:150]
    return ""


async def page_text(bm: Any) -> str:
    from core.watch_observe import _result_text

    try:
        return _result_text(await bm.call_tool("browser_extract", {}))
    except Exception:
        return ""


async def session_state(bm: Any) -> tuple[str, list[str], list[str]]:
    """What the page says the session is now: ``logged_in`` / ``logged_out``
    / ``unclear``, with the words that decided it."""
    from core.watch_observe import _result_text

    try:
        text = _result_text(await bm.call_tool("browser_extract", {})).lower()
    except Exception:
        text = ""
    strong = sorted({w for w in LOGGED_IN_STRONG if w in text})
    weak = sorted({w for w in LOGGED_IN_WEAK if w in text})
    hits_out = sorted({w for w in LOGGED_OUT_WORDS if w in text})
    # A wallet balance reads "GC 5,000 · SC 2.00" — the code BEFORE the
    # number; an offer reads "5,000 GC" (Pulsz and Hello Millions,
    # 2026-09-02: both lobbies were live sessions judged "no form").
    balance = bool(_BALANCE_RE.search(text)) and not hits_out
    if balance:
        strong = strong + ["coin balance shown"]
    hits_in = strong + weak
    if strong and len(hits_out) <= len(hits_in):
        return "logged_in", hits_in[:4], hits_out[:3]
    if strong:
        return "unclear", hits_in[:4], hits_out[:3]
    if weak and not hits_out:
        return "unclear", hits_in[:4], hits_out[:3]     # coins talk, no controls either way
    return "logged_out", hits_in[:4], hits_out[:3]


async def settled_session_state(bm: Any, *, tries: int = 3, wait_ms: int = 3000) -> tuple[str, list[str], list[str]]:
    """These lobbies are JS apps: three seconds after navigation the page
    can still be a spinner, and an empty page reads as logged out. Wait
    until the page has words, then judge."""
    from core.watch_observe import _result_text

    state, hits_in, hits_out = "logged_out", [], []
    for i in range(max(1, tries)):
        try:
            text = _result_text(await bm.call_tool("browser_extract", {}))
        except Exception:
            text = ""
        state, hits_in, hits_out = await session_state(bm)
        if state == "logged_in" or len(text.split()) >= 40:
            break
        if i + 1 < tries:
            await bm.call_tool("browser_wait", {"ms": wait_ms})
    return state, hits_in, hits_out


async def wait_out_challenge(bm: Any, seconds: int) -> str:
    """An image/audio puzzle appeared. The organ does not solve one — but
    an operator can, in the visible Chrome window, once per brand: the
    session then lives in the browser profile and later collection runs
    unattended. Returns ``passed`` / ``challenge``."""
    for _ in range(max(1, int(seconds) // 3)):
        await bm.call_tool("browser_wait", {"ms": 3000})
        w = await _widget(bm)
        if w.get("token") or not w.get("challenge"):
            return "passed"
        if not await has_password_field(bm):  # form submitted meanwhile
            return "passed"
    return "challenge"


async def switch_browser_exit(bm: Any, proxy_cfg: Any, state: str) -> tuple[bool, dict[str, Any]]:
    """Point the browser at the exit serving ``state``, and PROVE it.

    These accounts are geo-bound — Chumba runs GeoComply — so a session
    opened from the wrong state can be refused with the right password,
    and a session opened from an unverified exit cannot honestly be
    called a session in that state. Returns ``(ok, detail)``; the browser
    is left on the new exit only when the check passed.
    """
    from core.watch_observe import (
        clear_exit_verification_cache,
        pin_password,
        verify_browser_exit,
    )

    want = (state or "").strip().upper()
    if not want or want == "N/A" or bm is None or proxy_cfg is None:
        return True, {"state": "n/a"}
    if getattr(bm, "_watch_exit_state", "") == want:
        return True, {"state": want, "cached": True}
    if not proxy_cfg.request_proxy_url(want):
        # No exit promises this state — never pretend one does.
        return False, {"error": f"no configured exit for {want}"}
    entry = proxy_cfg.exit_for_state(want) or {}
    host = str(entry.get("host") or proxy_cfg.host)
    port = int(entry.get("port") or proxy_cfg.port)
    scheme = str(entry.get("type") or proxy_cfg.type or "http")
    try:
        await bm.close()  # the exit is chosen at launch; a new one needs a new Chrome
    except Exception as e:
        logger.debug("watch_login: browser close before exit switch: %s", e)
    bm.proxy_server = f"{scheme}://{host}:{port}"
    bm.proxy_username = str(entry.get("username") or proxy_cfg.username)
    bm.proxy_password = pin_password(str(entry.get("password") or proxy_cfg.password))
    bm.proxy_bypass = list(getattr(proxy_cfg, "bypass", []) or [])
    clear_exit_verification_cache()
    ok, detail = await verify_browser_exit(bm, want)
    if ok:
        bm._watch_exit_state = want
    return ok, {**detail, "state": want}


def recent_attempt(results_path: str, brand: str, *, within_hours: float) -> dict[str, Any] | None:
    """The last verdict for this brand, if it is still fresh.

    Repeated sign-in attempts are how accounts get locked: every failure
    counts against the brand's own limiter, and "Login failed, please try
    again" is what a limiter says too. So a brand checked recently is not
    checked again — the cache is a safety rail, not an optimisation.
    """
    from datetime import UTC, datetime
    from pathlib import Path as _P

    try:
        rows = json.loads(_P(results_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    now = datetime.now(UTC)
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("brand")) != brand or not row.get("checked_at"):
            continue
        try:
            when = datetime.fromisoformat(str(row["checked_at"]))
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if (now - when).total_seconds() <= within_hours * 3600:
            return row
    return None


async def login_to_site(
    bm: Any,
    creds: dict[str, Any],
    *,
    screenshot_path: str = "",
    assist_seconds: int = 0,
    exit_state: str = "",
) -> dict[str, Any]:
    """Log the browser into one brand. Never raises; the verdict is read
    from the page, so a failure cannot be reported as a session.

    ``exit_state`` only labels the result — the caller switches the exit
    (:func:`switch_browser_exit`) so one switch can serve many brands."""
    from datetime import UTC, datetime
    brand = str(creds.get("brand") or "")
    url = str(creds.get("url") or "")
    out: dict[str, Any] = {"brand": brand, "url": url, "verdict": "error", "note": ""}
    if exit_state:
        out["exit_state"] = exit_state
    if bm is None or not url:
        out["note"] = "no browser or no url"
        return out
    try:
        for attempt in range(2):  # the first navigation can hit a proxy handshake
            await bm.call_tool("browser_navigate", {"url": url})
            await bm.call_tool("browser_wait", {"ms": 3000})
            here = str(await _eval(bm, "location.href") or "")
            if not here.startswith("chrome-error"):
                break
            if attempt:
                out.update(verdict="unreachable", note="navigation failed twice")
                return out
        state, _, _ = await settled_session_state(bm)
        if state == "logged_in":
            out.update(verdict="already_logged_in", note="session already active")
        else:
            note = await open_login_form(bm, url, str(creds.get("username") or ""))
            if not await has_password_field(bm):
                # No password field is what a LIVE session looks like too:
                # the click landed on nothing and the lobby is behind it.
                state, hits_in, _ = await settled_session_state(bm, tries=2)
                if state == "logged_in":
                    out.update(verdict="already_logged_in",
                               note=f"session already active ({', '.join(hits_in[:3])}); {note}")
                else:
                    out.update(verdict="no_form", note=note)
            else:
                note += "; " + await fill_and_submit(
                    bm,
                    str(creds.get("username") or ""),
                    str(creds.get("password") or ""),
                )
                if "captcha challenge" in note and assist_seconds > 0:
                    logger.info(
                        "watch_login: %s shows an anti-bot puzzle — waiting %ss for a human",
                        brand, assist_seconds,
                    )
                    if await wait_out_challenge(bm, assist_seconds) == "passed":
                        note += "; challenge cleared by operator; " + await submit_login_form(bm)
                        await bm.call_tool("browser_wait", {"ms": 7000})
                state, hits_in, hits_out = await session_state(bm)
                rejection = login_error(await page_text(bm)) if state != "logged_in" else ""
                if state == "logged_in":
                    out.update(verdict="logged_in", note=note)
                elif rejection:
                    # The site ANSWERED — the form went through and was
                    # refused. Why is not knowable from here: a wrong
                    # password, an account state, or an invisible anti-bot
                    # score can all produce the same words. Report what it
                    # said and let a human read it.
                    out.update(verdict="rejected", note=note, message=rejection)
                elif "captcha challenge" in note:
                    out.update(verdict="challenge", note=note)
                else:
                    out.update(verdict=state, note=note)
                out["signals_in"] = hits_in
                out["signals_out"] = hits_out
        if screenshot_path:
            try:
                from pathlib import Path as _P

                target = _P(screenshot_path).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                await bm.call_tool("browser_capture", {"path": str(target)})
                out["screenshot"] = str(target)
            except Exception as e:  # a missing picture is not a failed login
                logger.debug("watch_login: capture failed: %s", e)
    except Exception as e:  # a login attempt never takes the caller down
        out.update(verdict="error", note=f"{type(e).__name__}: {e}")
    out["checked_at"] = datetime.now(UTC).isoformat()
    return out
