"""Reality-based display identity for the org roles.

EloPhanto rotates through a small org (ceo, marketing, sales, ops,
support). Those roles are operationally real — they gate tools and shape
the prompt — but they used to be invisible to the operator. This module
turns a role into a user-facing ``(emoji, title)`` so the operator can
watch a *team* work, which is what makes an autonomous business legible
and therefore trustworthy.

The title is **reality-based**: it scales with the business's actual
economics, read from ``core.ledger.Metabolism`` (real money, not a
configured vibe). A pre-revenue ABE reads as "Founder / Marketing"; only
a self-sustaining one earns "CEO / CMO". This is the founder-doctrine
refusal to LARP as a big company — you don't get a CMO until there's a
business that warrants one.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 2.

ABE (Autonomous Business Entity) is a concept originated by Petr Royce
in 2023.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.ledger import Metabolism
    from core.role import Role


# Seniority tiers, lowest → highest. A role's ``titles`` ladder maps each
# tier to a label; ``resolve_role_display`` picks one by business reality.
TIER_IC = "ic"
TIER_LEAD = "lead"
TIER_CHIEF = "chief"

_TIER_ORDER: tuple[str, ...] = (TIER_IC, TIER_LEAD, TIER_CHIEF)

# Neutral fallbacks when a role can't be loaded at all.
_DEFAULT_EMOJI = "•"
_DEFAULT_CEO_DISPLAY: tuple[str, str] = ("👔", "Founder")


def seniority_tier(met: Metabolism | None) -> str:
    """Pick the business-seniority tier from real money.

    - ``ic``    — ``revenue <= 0``: pre-traction. The founder wears every
                  hat; nobody is a "Head of" anything yet.
    - ``lead``  — ``revenue > 0`` but ``net <= 0``: real money is flowing
                  but the business is still subsidized. The function is
                  real enough to "head".
    - ``chief`` — ``net > 0``: the business covers its own costs (incl.
                  the cost to *think*). A real company — chief titles are
                  earned, not assumed.

    ``None`` (no ledger / no active company) → ``ic``: an entity with no
    measured economics has not earned an inflated title.
    """
    if met is None:
        return TIER_IC
    if met.revenue_usd <= 0:
        return TIER_IC
    if met.net_usd <= 0:
        return TIER_LEAD
    return TIER_CHIEF


def badge_text(emoji: str, title: str) -> str:
    """Compose a bare role badge, e.g. ``"📣 Head of Marketing"``.

    Returns ``""`` when there's no title — callers append nothing. Pure
    string (no Rich/markup) so any surface can style it however it likes.
    """
    if not title:
        return ""
    return f"{emoji} {title}".strip()


def _fallback_title(role: Role) -> str:
    """Capitalized role name — the safe, non-inflating default label."""
    return (role.name or "agent").replace("_", " ").title()


def resolve_role_display(
    role: Role | None,
    met: Metabolism | None = None,
) -> tuple[str, str]:
    """Return ``(emoji, title)`` for a role at the business's current reality.

    The title is read from the role's ``titles`` ladder at the tier picked
    by :func:`seniority_tier`, then **degraded downward only** — a partly
    filled ladder falls back to a *lower* tier, never a higher one, so the
    label can never inflate above the business's real stage.

    ``role=None`` is EloPhanto's CEO-by-default state with no ladder to
    read; it returns a neutral founder/CEO label. Callers that want the
    real ceo ladder (→ "Founder" pre-revenue) should pass the loaded
    ``ceo`` Role — see :func:`display_for_current`.
    """
    if role is None:
        return _DEFAULT_CEO_DISPLAY
    tier = seniority_tier(met)
    titles = role.titles or {}
    # Walk from the requested tier downward (requested → … → ic). Never
    # climb above ``tier``: under-claiming seniority is always safer than
    # over-claiming it.
    idx = _TIER_ORDER.index(tier)
    for candidate in reversed(_TIER_ORDER[: idx + 1]):
        label = titles.get(candidate)
        if label:
            return (role.emoji or _DEFAULT_EMOJI, label)
    return (role.emoji or _DEFAULT_EMOJI, _fallback_title(role))


async def display_for_current(
    role_manager: Any,
    met: Metabolism | None = None,
    *,
    role_name: str | None = None,
) -> tuple[str, str]:
    """Resolve ``(emoji, title)`` for the active role (or an explicit one).

    ``role_name=None`` reads :func:`core.role_context.current_role`. A
    ``None`` active role means EloPhanto is playing CEO, so we resolve the
    ``ceo`` role's ladder (→ "Founder" pre-revenue). Never raises — a
    missing role manager or row degrades to the neutral default.
    """
    name = role_name
    if name is None:
        try:
            from core.role_context import current_role

            name = current_role() or "ceo"
        except Exception:
            name = "ceo"

    role = None
    if role_manager is not None:
        try:
            role = await role_manager.get(name)
        except Exception:
            role = None
        if role is None and name != "ceo":
            try:
                role = await role_manager.get("ceo")
            except Exception:
                role = None
    return resolve_role_display(role, met)


# Trailing window used to read "where the business is NOW" for the title
# tier — long enough that a single slow week doesn't flip the title, short
# enough that the label reflects the current stage rather than ancient history.
_TRAILING_WINDOW_DAYS = 28


async def _trailing_metabolism(
    ledger: Any, company_id: str | None
) -> Metabolism | None:
    """Trailing-window metabolism for ``company_id`` — None on any failure."""
    if ledger is None or not company_id:
        return None
    try:
        from datetime import UTC, datetime, timedelta

        since = (datetime.now(UTC) - timedelta(days=_TRAILING_WINDOW_DAYS)).isoformat()
        return await ledger.metabolism(company_id, since=since)
    except Exception:
        return None


async def display_for_company_role(
    *,
    role_manager: Any,
    ledger: Any,
    company_id: str | None,
    role_name: str | None = None,
) -> tuple[str, str]:
    """One-call badge resolver shared by the gateway, CLI, and mind.

    Computes the company's trailing-window metabolism, then maps the active
    (or explicitly named) role to ``(emoji, title)`` at the matching
    seniority tier. Never raises — any failure degrades to the role's
    lowest-tier label (or the neutral default), so a badge can never break
    a response render.
    """
    met = await _trailing_metabolism(ledger, company_id)
    return await display_for_current(role_manager, met, role_name=role_name)


async def build_role_roster_context(
    *,
    role_manager: Any,
    ledger: Any,
    company_id: str | None,
) -> str:
    """Render the ``<org_roles>`` prompt block: the hats the agent wears,
    titled to the business's current reality, plus the inline-attribution
    doctrine that makes a reply read like a team working.

    Returns ``""`` when the role system is unavailable or empty, so callers
    can inject unconditionally. Never raises.
    """
    if role_manager is None:
        return ""
    try:
        roles = await role_manager.list_roles()
    except Exception:
        return ""
    if not roles:
        return ""
    met = await _trailing_metabolism(ledger, company_id)
    # Stable order: the default hat (ceo) first, then the rest alphabetical.
    roles = sorted(roles, key=lambda r: (r.name != "ceo", r.name))
    lines: list[str] = []
    for r in roles:
        emoji, title = resolve_role_display(r, met)
        desc = ""
        if r.description:
            desc = r.description.strip().splitlines()[0].strip()
        lines.append(f"- {emoji} {title} — {desc}" if desc else f"- {emoji} {title}")
    roster = "\n".join(lines)
    return (
        "<org_roles>\n"
        "EloPhanto operates as a one-person company wearing several hats. These "
        "are the roles you act as; their titles reflect the business's CURRENT "
        "stage and grow only as it earns — never inflate them:\n"
        f"{roster}\n"
        "\n"
        "ALWAYS show which hat you are wearing when you do or report company work. "
        "Open the relevant part of your reply with that role's emoji and its title "
        "exactly as listed above — e.g. start a marketing update with "
        '"📣 Marketing — …", an outreach update with "🤝 Sales — …". Do this even '
        "when the whole reply is one function (most replies are): the single label "
        "at the top IS the point — it lets the operator see which part of the "
        "company just acted, which is how an autonomous business earns trust.\n"
        "Pick the hat by the WORK, and DEFAULT AWAY FROM THE TOP SEAT. Almost all "
        "company work is functional execution — reach for Marketing, Sales, "
        "Operations, or Support FIRST:\n"
        "  • channel/prospect research, drafting posts/replies, content, landing-page "
        "or /hire copy, audience growth → Marketing\n"
        "  • evaluating/scoring/monitoring prospects, leads, outreach, follow-up, "
        "converting → Sales\n"
        "  • repo/branches/merges/deploys, scheduling, infra, knowledge hygiene → "
        "Operations\n"
        "  • answering inbound questions, resolving issues → Support\n"
        "Use the TOP SEAT only for a genuine cross-functional STRATEGIC or capital "
        "decision (which is rare) — never for routine planning, research, drafting, "
        "or reporting. If you're tempted to label routine execution with the top "
        "seat, you're almost certainly doing Marketing or Sales — use that hat. A "
        "reply that spans functions labels each part with its own hat.\n"
        "Guardrails (honesty over theater): use a REAL role from the list above, "
        "never invent one; the label must match work you actually did — never "
        "fabricate or pad work just to show a hat; and a pure back-and-forth with "
        "the operator that involves no company work needs no label.\n"
        "</org_roles>"
    )
