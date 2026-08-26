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
from typing import Any

logger = logging.getLogger(__name__)

# What a logged-in session shows, and what a logged-out one still shows.
LOGGED_IN_WORDS = (
    "log out", "logout", "sign out", "my account", "account settings",
    "gold coins balance", "sweeps coins", "cashier", "redeem", "buy coins",
    "wallet", "vip level", "claim daily", "daily bonus claim", "my profile",
)
LOGGED_OUT_WORDS = (
    "log in", "login", "sign in", "create account", "register", "join now",
)
LOGIN_ENTRY = ("Log In", "Login", "Sign In", "Sign in", "LOG IN", "LOGIN")
SWITCH_TO_LOGIN = (
    "already got an account", "already have an account", "log in",
    "login", "sign in", "existing player",
)
SUBMIT_LABELS = (
    "Log In", "Login", "Sign In", "Continue", "Submit", "LOG IN", "LOGIN NOW",
)
LOGIN_PATHS = ("/login", "/log-in", "/signin", "/sign-in", "/account/login")

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


async def open_login_form(bm: Any, url: str) -> str:
    """Get a visible password field on screen. Returns a short note."""
    from core.watch_observe import dismiss_consent

    note = ""
    base = url.rstrip("/")
    if await has_password_field(bm):
        return "form already open"
    for path in LOGIN_PATHS:
        await bm.call_tool("browser_navigate", {"url": base + path})
        await bm.call_tool("browser_wait", {"ms": 3500})
        await dismiss_consent(bm)
        if await has_password_field(bm):
            return f"form at {path}"
    # No login route: the header control, then the "already have an
    # account" link several brands hide the real form behind.
    await bm.call_tool("browser_navigate", {"url": url})
    await bm.call_tool("browser_wait", {"ms": 3000})
    await dismiss_consent(bm)
    for label in LOGIN_ENTRY:
        matched = (await _click_text(bm, label)).lower()
        if matched and label.lower() in matched:
            note = f"opened via '{label}'"
            break
    await bm.call_tool("browser_wait", {"ms": 3000})
    if not await has_password_field(bm):
        for label in SWITCH_TO_LOGIN:
            matched = (await _click_text(bm, label, exact=False)).lower()
            if matched and label.split()[0] in matched:
                await bm.call_tool("browser_wait", {"ms": 3000})
                if await has_password_field(bm):
                    note += f"; switched via '{matched[:24]}'"
                    break
    return note or "no form found"


_SUBMIT_JS = (
    "(() => {"
    "const pw = [...document.querySelectorAll('input[type=password]')]"
    ".filter(e => e.offsetParent !== null)[0];"
    "if (!pw) return 'no-password';"
    "const scope = pw.closest('form') || pw.closest('div[class*=modal],div[class*=login],section') "
    "|| document.body;"
    "const words = /(log ?in|sign ?in|continue|submit)/i;"
    "let btn = scope.querySelector('button[type=submit],input[type=submit]');"
    "if (!btn) {"
    "  const cands = [...scope.querySelectorAll('button,[role=button],a')]"
    "    .filter(b => b.offsetParent !== null && !b.disabled && words.test(b.innerText || b.value || ''));"
    "  btn = cands[0];"
    "}"
    "if (!btn) return 'no-button';"
    "if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') return 'disabled';"
    "btn.scrollIntoView({block: 'center'}); btn.click();"
    "return 'clicked:' + ((btn.innerText || btn.value || 'submit').trim().slice(0, 20));})()"
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
    if got.startswith("clicked:"):
        return f"submitted via '{got[8:]}'"
    if got == "disabled":
        return "submit disabled (anti-bot or validation)"
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


async def session_state(bm: Any) -> tuple[str, list[str], list[str]]:
    """What the page says the session is now: ``logged_in`` / ``logged_out``
    / ``unclear``, with the words that decided it."""
    from core.watch_observe import _result_text

    try:
        text = _result_text(await bm.call_tool("browser_extract", {})).lower()
    except Exception:
        text = ""
    hits_in = sorted({w for w in LOGGED_IN_WORDS if w in text})
    hits_out = sorted({w for w in LOGGED_OUT_WORDS if w in text})
    if hits_in and len(hits_out) <= len(hits_in):
        return "logged_in", hits_in[:4], hits_out[:3]
    if hits_in:
        return "unclear", hits_in[:4], hits_out[:3]
    return "logged_out", hits_in, hits_out[:3]


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


async def login_to_site(
    bm: Any,
    creds: dict[str, Any],
    *,
    screenshot_path: str = "",
    assist_seconds: int = 0,
) -> dict[str, Any]:
    """Log the browser into one brand. Never raises; the verdict is read
    from the page, so a failure cannot be reported as a session."""
    brand = str(creds.get("brand") or "")
    url = str(creds.get("url") or "")
    out: dict[str, Any] = {"brand": brand, "url": url, "verdict": "error", "note": ""}
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
        state, _, _ = await session_state(bm)
        if state == "logged_in":
            out.update(verdict="already_logged_in", note="session already active")
        else:
            note = await open_login_form(bm, url)
            if not await has_password_field(bm):
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
                if state == "logged_in":
                    out.update(verdict="logged_in", note=note)
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
    return out
