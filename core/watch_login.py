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
# A second step after the password: the site accepted the credentials and
# now wants a code it sent somewhere (WOW Vegas, 2026-09-02: "We've
# detected a login from a new device or browser. Please enter the
# verification code sent to your email").
VERIFICATION_PHRASES = (
    "verification code", "enter the code", "code sent to", "code we sent", "one-time code",
    "one time code", "two-factor", "2-step", "two step verification", "authenticator app",
    "new device or browser",
)
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


# The visible login control, the way a person finds it: text on screen
# that says Log In / Sign In, in the header first. Only elements that are
# actually on screen count — a hidden template's "Log In" is what the
# text matcher hit on Spinfinite (2026-09-02) while the real button sat
# top right; and no URL is ever guessed: the browser drives the site.
_VISIBLE_LOGIN_JS = (
    "(() => {"
    "const rx = %s;"
    "const out = [];"
    "const vw = window.innerWidth, vh = window.innerHeight;"
    "for (const el of document.querySelectorAll('a,button,[role=button],input[type=submit],span,div,li')) {"
    "  const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();"
    "  if (!t || t.length > 40 || !rx.test(t)) continue;"
    "  if (el.children.length > 3) continue;"
    "  if (el.offsetParent === null && el.tagName !== 'BODY') continue;"
    "  const r = el.getBoundingClientRect();"
    "  if (r.width < 8 || r.height < 8 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;"
    "  const st = getComputedStyle(el);"
    "  if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity || '1') < 0.05) continue;"
    "  out.push({text: t, x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height});"
    "}"
    "out.sort((a, b) => (a.y - b.y) || (b.x - a.x));"
    "return JSON.stringify(out.slice(0, 6));})()"
)
_LOGIN_WORDS = "/^(log ?in|sign ?in|log ?in now|sign ?in now)$/i"
_SWITCH_WORDS = "/(already (got|have) an account|existing (player|member|account)|have an account\\??\\s*(log|sign) ?in)/i"


async def visible_controls(bm: Any, words_regex: str) -> list[dict[str, Any]]:
    raw = await _eval(bm, _VISIBLE_LOGIN_JS % words_regex, max_length=4000)
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        return []
    return [it for it in items if isinstance(it, dict) and it.get("text")]


async def click_visible(bm: Any, words_regex: str, *, skip: int = 0) -> str:
    """Click the visible control whose text matches, by its on-screen
    coordinates — a real click on the real button. Returns the text
    clicked, "" when nothing visible matches."""
    cands = await visible_controls(bm, words_regex)
    if len(cands) <= skip:
        return ""
    c = cands[skip]
    try:
        await bm.call_tool("browser_click_at", {"x": round(float(c["x"])), "y": round(float(c["y"]))})
    except Exception:
        return ""
    return str(c["text"])


# ── The agent drives ─────────────────────────────────────────────────
# The general-purpose agent already knows how to work a site: look, click
# what is on screen, look again (the browser playbook, evidence gating,
# stagnation detection). The script above is the fallback when no agent
# is wired in. With one, the agent gets the form on screen and the code
# keeps the rules: it never sees a secret, it cannot navigate to an
# address, it types nothing (docs/90).
AGENT_BROWSER_TOOLS: frozenset[str] = frozenset({
    "browser_click", "browser_click_text", "browser_click_at", "browser_press_key",
    "browser_select_option", "browser_scroll", "browser_scroll_container",
    "browser_hover", "browser_hover_element", "browser_go_back",
    "browser_extract", "browser_read_semantic", "browser_get_elements", "browser_screenshot",
    "browser_get_html", "browser_get_element_html", "browser_get_element_box",
    "browser_get_meta", "browser_dom_search", "browser_inspect_element",
    "browser_wait", "browser_wait_for_selector",
})
OPEN_FORM_GOAL = """You are already on {url} in the agent's own Chrome. Your job: get the site's
SIGN-IN form (an e-mail/username field and a password field) on screen, the way a
person would, and stop. Do not type anything into it — you have no credentials and
must not invent any.

How to work: look at the page first (browser_get_elements or browser_screenshot),
then act, then look again before the next action. Clear a cookie banner if one is
in the way. Find the control a visitor would use to sign in — usually a header
button reading Log In / Login / Sign In — and click THAT visible element (by index
from browser_get_elements is safest). If the click opens a SIGN-UP panel, find its
"already have an account" / "log in" switch inside the panel and click it. If the
form appears one step at a time (e-mail first), stop as soon as the first field is
on screen. Wait a few seconds for panels to animate.

Never guess an address: you cannot navigate, and you must not try to reach a URL
you assume exists. If a side menu, drawer or overlay opens and hides the header,
close it (its X, or Escape) and look again — the sign-in control is usually in the
header, not in the menu. If nothing you can see leads to a form after a genuine
try, say so. Budget: you have about {max_steps} actions; report by action
{report_by} at the latest, whatever the state — a report with no_form beats no
report.

Stop conditions — finish with EXACTLY these two lines and nothing after them:
STATE: form_on_screen | already_signed_in | challenge | no_form
PROOF: <a short phrase copied exactly from the page that shows the state — the
field label you see, the balance/logout control that proves a signed-in account,
the captcha wording, or the last thing you clicked>"""


async def agent_opens_form(agent: Any, url: str, *, timeout: float = 240.0, max_steps: int = 18) -> dict[str, Any]:
    """Delegate 'get the sign-in form on screen' to the agent itself, with
    browser tools only and no navigation tool at all. Returns
    ``{state, proof, steps, tools, note}``; never raises."""
    import asyncio

    out: dict[str, Any] = {"state": "error", "proof": "", "steps": 0, "tools": [], "note": ""}
    if agent is None:
        out["note"] = "no agent"
        return out
    try:
        all_names = {t.name for t in agent._registry.all_tools()}
    except Exception:
        all_names = set()
    excluded = {n for n in all_names if n not in AGENT_BROWSER_TOOLS}
    try:
        resp = await asyncio.wait_for(
            agent.run_isolated(
                OPEN_FORM_GOAL.format(url=url, max_steps=max_steps, report_by=max(4, max_steps - 4)),
                excluded_tool_names=excluded, max_steps_override=max_steps,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        out["note"] = f"agent timed out after {timeout:.0f}s"
        return out
    except Exception as e:
        out["note"] = f"agent failed: {type(e).__name__}: {e}"
        return out
    text = str(getattr(resp, "content", "") or "")
    out["steps"] = int(getattr(resp, "steps_taken", 0) or 0)
    out["tools"] = sorted(set(getattr(resp, "tool_calls_made", []) or []))
    m = re.search(r"STATE:\s*([a-z_]+)", text, re.I)
    p = re.search(r"PROOF:\s*(.+)", text, re.I)
    out["state"] = (m.group(1).lower() if m else "unclear")
    out["proof"] = " ".join(p.group(1).split())[:200] if p else ""
    out["note"] = " ".join(text.split())[-300:]
    if not m and out["steps"] >= max_steps:
        # Ran out of actions without reporting: that is a miss, not a mystery.
        out["state"] = "no_form"
        out["note"] = f"used all {max_steps} actions without reaching a form; last words: {out['note'][-160:]}"
    return out


SUBMIT_GOAL = """The sign-in form on screen is already filled in. Click the form's OWN submit
button — the one inside the form, reading Log In / Sign In / Continue — and
nothing else: not a header link, not a "Continue with Google/Apple/Facebook"
button. Look first (browser_get_elements), click it by index, wait three
seconds, look again. Then finish with EXACTLY:
STATE: submitted | not_found
PROOF: <the button text you clicked, copied exactly, or what you saw instead>"""


async def agent_submits_form(agent: Any, *, timeout: float = 90.0) -> dict[str, Any]:
    import asyncio

    out: dict[str, Any] = {"state": "error", "proof": "", "note": ""}
    if agent is None:
        return out
    try:
        all_names = {t.name for t in agent._registry.all_tools()}
    except Exception:
        all_names = set()
    excluded = {n for n in all_names if n not in AGENT_BROWSER_TOOLS}
    try:
        resp = await asyncio.wait_for(
            agent.run_isolated(SUBMIT_GOAL, excluded_tool_names=excluded, max_steps_override=8),
            timeout=timeout,
        )
    except Exception as e:
        out["note"] = f"agent failed: {type(e).__name__}: {e}"
        return out
    text = str(getattr(resp, "content", "") or "")
    m = re.search(r"STATE:\s*([a-z_]+)", text, re.I)
    p = re.search(r"PROOF:\s*(.+)", text, re.I)
    out["state"] = (m.group(1).lower() if m else "unclear")
    out["proof"] = " ".join(p.group(1).split())[:200] if p else ""
    return out


async def open_login_form(bm: Any, url: str, username: str = "") -> str:
    """Get a visible password field on screen, the way a person does it:
    click the login control that is ON SCREEN; when that opens a SIGN-UP
    panel — as several of these brands do — click its "already have an
    account" switch; complete an e-mail-first step when there is one.
    Never a guessed address: the browser drives the site, and when no
    visible control leads to a form, that is the answer. Returns a note."""
    from core.watch_observe import dismiss_consent

    if await has_password_field(bm):
        return "form already open"
    notes: list[str] = []
    # Clear the consent overlay FIRST: while it is up the login control is
    # not reachable and the click lands on the banner (High 5, 2026-08-26).
    await dismiss_consent(bm)
    for attempt in range(2):                      # the header button, then the hero's
        clicked = await click_visible(bm, _LOGIN_WORDS, skip=attempt)
        if not clicked and attempt == 0:
            # Nothing the DOM query can see (a shadow root): the bridge's
            # own matcher pierces those — still a click, never a URL.
            for label in LOGIN_ENTRY:
                matched = await _click_text(bm, label)
                if matched and label.lower() in matched.lower():
                    clicked = matched.strip()
                    break
        if not clicked:
            break
        notes.append(f"clicked '{clicked[:18]}'")
        if await _wait_for_form(bm, 12):
            return "; ".join(notes)
        await dismiss_consent(bm)
        step = await _email_first_step(bm, username)
        if step:
            notes.append(step)
            return "; ".join(notes)
        # A sign-up panel: the real login hides behind its switch link.
        switched = await click_visible(bm, _SWITCH_WORDS)
        if not switched:
            for label in SWITCH_TO_LOGIN:
                matched = await _click_text(bm, label, exact=False)
                if matched and label.split()[0] in matched.lower():
                    switched = matched.strip()
                    break
        if switched:
            notes.append(f"switched via '{switched[:22]}'")
            if await _wait_for_form(bm, 10):
                return "; ".join(notes)
            step = await _email_first_step(bm, username)
            if step:
                notes.append(step)
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


def verification_prompt(text: str) -> str:
    """The site's own words when it asks for a second step, else ''."""
    low = (text or "").lower()
    for phrase in VERIFICATION_PHRASES:
        i = low.find(phrase)
        if i >= 0:
            start = max(0, i - 80)
            return " ".join(text[start : i + 100].split())[:180]
    return ""


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
    """What a person sees: the whole visible page. ``browser_extract``
    returns only the page's <main> element — on Pulsz that is the offer
    banners and the grid, while the balance, the points, the customer id
    and the Logout control sit in the header, the sidebar and a modal
    (2026-09-02: a live session judged logged out twice on that slice)."""
    from core.watch_observe import _result_text, html_to_text

    try:
        body = await _eval(bm, "document.body ? document.body.innerText : ''", max_length=20000)
        if isinstance(body, str) and len(body.split()) >= 5:
            return body
    except Exception:
        pass
    try:
        text = _result_text(await bm.call_tool("browser_extract", {}))
        if text.strip():
            return text
    except Exception:
        pass
    try:
        return html_to_text(_result_text(await bm.call_tool("browser_get_html", {"maxLength": 400000})))
    except Exception:
        return ""


async def session_state(bm: Any) -> tuple[str, list[str], list[str]]:
    """What the page says the session is now: ``logged_in`` / ``logged_out``
    / ``unclear``, with the words that decided it."""
    text = (await page_text(bm)).lower()
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


SESSION_JUDGE_SYSTEM = """You are looking at the text of one page of a social casino site, as
the agent's browser rendered it. Decide whether the browser is signed in
to a player account on this page.

Signed in looks like: a wallet balance (e.g. "GC 5,000", "SC 2.00"), a
player level or points, a customer/account id, a Logout control, a
"my account" area, a claimable daily bonus. Signed out looks like: Log
In / Sign Up controls, a welcome offer addressed to new players, a
login form. A captcha or "verify you are human" is a challenge.

A message that the sign-in was refused ("Login failed", "incorrect
password", "account locked", "try again later") is a rejection. A page
asking for a verification code, a one-time code sent by e-mail or SMS,
or an authenticator ("new device", "enter the code we sent") is
verification_required — the credentials were accepted and a second
step is pending.

Return STRICT JSON: {"state": "logged_in" | "logged_out" | "rejected" | "verification_required" | "challenge" | "unclear",
 "evidence": "<a short phrase copied EXACTLY from the page that proves it>",
 "why": "<one plain sentence>"}
The evidence must be verbatim from the page; if nothing on the page
proves either state, say unclear."""


async def judge_session(router: Any, text: str) -> tuple[str, str]:
    """The agent's own reading of the page when the keyword check cannot
    tell. Returns ``(state, evidence)``; the evidence must be printed on
    the page or the verdict is discarded — the same rule every other
    claim in this organ obeys. Never raises."""
    if router is None or not (text or "").strip():
        return "unclear", ""
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": SESSION_JUDGE_SYSTEM},
                {"role": "user", "content": json.dumps({"page_text": text[:12000]})},
            ],
            task_type="analysis",
            temperature=0.0,
            max_tokens=200,
        )
        body = (resp.content or "").strip()
        if body.startswith("```"):
            parts = body.split("```")
            body = parts[1] if len(parts) > 1 else body
            body = body[4:] if body.startswith("json") else body
        raw = json.loads(body)
        state = str(raw.get("state") or "unclear").strip().lower()
        evidence = " ".join(str(raw.get("evidence") or "").split())
    except Exception as e:
        logger.debug("watch_login: session judgement failed: %s", e)
        return "unclear", ""
    if state not in ("logged_in", "logged_out", "rejected", "verification_required", "challenge"):
        return "unclear", ""
    norm = " ".join(text.split()).lower()
    if not evidence or evidence.lower() not in norm:
        return "unclear", ""             # a verdict without printed proof is no verdict
    return state, evidence


async def settled_session_state(bm: Any, *, tries: int = 3, wait_ms: int = 3000) -> tuple[str, list[str], list[str]]:
    """These lobbies are JS apps: three seconds after navigation the page
    can still be a spinner, and an empty page reads as logged out. Wait
    until the page has words, then judge."""
    state, hits_in, hits_out = "logged_out", [], []
    for i in range(max(1, tries)):
        text = await page_text(bm)
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
    router: Any = None,
    agent: Any = None,
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
        from core.watch_observe import dismiss_consent

        await dismiss_consent(bm)   # the banner's text is not the page's
        state, hits_in, _ = await settled_session_state(bm)
        judged = await page_text(bm)
        out["page_excerpt"] = " ".join(judged.split())[:240]   # what the verdict was read from
        proof = ", ".join(hits_in[:3])
        if state != "logged_in" and router is not None:
            # The keyword check could not tell: let the agent read the page.
            m_state, evidence = await judge_session(router, judged)
            if m_state == "logged_in":
                state, proof = "logged_in", f"model: {evidence}"
        if state == "logged_in":
            out.update(verdict="already_logged_in", note=f"session already active ({proof})")
        else:
            username = str(creds.get("username") or "")
            decided = False
            if agent is not None:
                # The agent gets the form on screen; the code types nothing yet.
                rep = await agent_opens_form(agent, url)
                out["agent"] = {k: rep[k] for k in ("state", "proof", "steps", "tools")}
                note = f"agent: {rep['state']} ({rep['proof'][:60]})" if rep["proof"] else f"agent: {rep['state']}"
                if rep["state"] == "already_signed_in":
                    m_state, evidence = await judge_session(router, await page_text(bm))
                    if m_state == "logged_in":
                        out.update(verdict="already_logged_in",
                                   note=f"session already active (model: {evidence}); {note}")
                        decided = True
                elif rep["state"] == "challenge":
                    w = await _widget(bm)
                    if w.get("kind") or w.get("challenge"):
                        out.update(verdict="challenge", note=f"anti-bot puzzle; {note}")
                        decided = True
                if not decided and rep["state"] in ("error", "unclear", "no_form") and not await has_password_field(bm):
                    note = await open_login_form(bm, url, username) + f"; {note}"   # the script, as the fallback
            else:
                note = await open_login_form(bm, url, username)
            if not decided and not await has_password_field(bm):
                step = await _email_first_step(bm, username)
                if step:
                    note += "; " + step
            if decided:
                pass
            elif not await has_password_field(bm):
                # No password field is what a LIVE session looks like too:
                # the click landed on nothing and the lobby is behind it.
                state, hits_in, _ = await settled_session_state(bm, tries=2)
                proof = ", ".join(hits_in[:3])
                if state != "logged_in" and router is not None:
                    m_state, evidence = await judge_session(router, await page_text(bm))
                    if m_state == "logged_in":
                        state, proof = "logged_in", f"model: {evidence}"
                if state == "logged_in":
                    out.update(verdict="already_logged_in", note=f"session already active ({proof}); {note}")
                else:
                    out.update(verdict="no_form", note=note)
            else:
                note += "; " + await fill_and_submit(
                    bm,
                    str(creds.get("username") or ""),
                    str(creds.get("password") or ""),
                )
                if agent is not None and "captcha challenge" not in note and await has_password_field(bm):
                    # The scorer's click did not take the form away: let the
                    # agent click the form's own button (no secrets involved).
                    sub = await agent_submits_form(agent)
                    note += f"; agent submit: {sub['state']}" + (f" ('{sub['proof'][:30]}')" if sub.get("proof") else "")
                    await bm.call_tool("browser_wait", {"ms": 7000})
                if "captcha challenge" in note and assist_seconds > 0:
                    logger.info(
                        "watch_login: %s shows an anti-bot puzzle — waiting %ss for a human",
                        brand, assist_seconds,
                    )
                    if await wait_out_challenge(bm, assist_seconds) == "passed":
                        note += "; challenge cleared by operator; " + await submit_login_form(bm)
                        await bm.call_tool("browser_wait", {"ms": 7000})
                state, hits_in, hits_out = await session_state(bm)
                final_text = await page_text(bm)
                rejection = login_error(final_text) if state != "logged_in" else ""
                second_step = verification_prompt(final_text) if state != "logged_in" else ""
                if router is not None and state != "logged_in":
                    m_state, evidence = await judge_session(router, final_text)
                    if m_state == "logged_in":
                        state, hits_in = "logged_in", hits_in + [f"model: {evidence}"]
                    elif m_state == "rejected" and not rejection:
                        rejection = evidence
                    elif m_state == "verification_required" and not second_step:
                        second_step = evidence
                out["page_excerpt"] = " ".join(final_text.split())[:240]
                if state == "logged_in":
                    out.update(verdict="logged_in", note=note)
                elif second_step:
                    # The credentials were ACCEPTED; the site wants a code it
                    # sent to the account's e-mail or phone. Not a failure —
                    # a step for whoever holds that inbox (or the agent's own
                    # inbox tools, when the account mail is the agent's).
                    out.update(verdict="verification_required", note=note, message=second_step)
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
