"""Seed packs for the competitive-intelligence organ.

A seed pack is a ready-made scoring frame — dimensions, weights, sub-criteria,
refresh cadences and alternative-view weightings — plus the brands to track.
The ``watch_*`` tools are market-agnostic; a pack is what makes them useful on
day one for a specific engagement.

``social_casino_t1`` encodes the Yellow Social Interactive scope of work:
Pulsz / Pulsz Bingo against 12 T1 sweepstakes-casino competitors across 12
weighted dimensions.

Cadences follow the SOW's refresh rule — promotional and marketing activity
weekly, operational dimensions monthly, financial and state-policy quarterly.

The two alternative views re-weight the SAME scores:
  * ``customer_proposition`` — games, promotions, loyalty, packages, RTP, payments
  * ``transition_priority``  — KYC, payments, loyalty capability, state variation,
    portfolio tooling (what YSI must actually build during the platform move)
Each view's weights sum to 100 independently so the two rankings stay comparable.
"""

from __future__ import annotations

from typing import Any

# ── Yellow Social Interactive — T1 social casino ────────────────────────

_SOW_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "Game portfolio and category range",
        "description": "Game portfolio, category range and content discovery.",
        "weight_pct": 12,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 18, "transition_priority": 12},
        "subcriteria": [
            {"name": "Category breadth", "weight_pct": 20},
            {"name": "Supplier breadth", "weight_pct": 15},
            {"name": "Content quality and popularity", "weight_pct": 20},
            {"name": "New-game cadence", "weight_pct": 15},
            {"name": "Navigation and discovery", "weight_pct": 15},
            {"name": "Bingo/cross-product relevance", "weight_pct": 15},
        ],
    },
    {
        "name": "Promotional proposition and generosity",
        "description": "Drives acquisition, conversion, reactivation and perceived value.",
        "weight_pct": 10,
        "refresh_cadence": "weekly",
        "view_weights": {"customer_proposition": 16, "transition_priority": 1},
        "subcriteria": [
            {"name": "Welcome-offer value", "weight_pct": 25},
            {"name": "Ongoing promotional frequency", "weight_pct": 20},
            {"name": "Personalisation and segmentation", "weight_pct": 20},
            {"name": "Clarity and simplicity", "weight_pct": 15},
            {"name": "Terms and playthrough conditions", "weight_pct": 10},
            {"name": "Originality and differentiation", "weight_pct": 10},
        ],
    },
    {
        "name": "Loyalty programme and proposition",
        "description": "Retention, frequency, VIP development and differentiation.",
        "weight_pct": 10,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 15, "transition_priority": 16},
        "subcriteria": [
            {"name": "Ease of understanding", "weight_pct": 15},
            {"name": "Progression mechanics", "weight_pct": 20},
            {"name": "Reward value", "weight_pct": 25},
            {"name": "Recognition and status", "weight_pct": 15},
            {"name": "VIP proposition", "weight_pct": 15},
            {"name": "Personalisation", "weight_pct": 10},
        ],
    },
    {
        "name": "KYC strategy and customer journey",
        "description": "Materially affects registration, purchase and redemption conversion.",
        "weight_pct": 10,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 2, "transition_priority": 22},
        "subcriteria": [
            {"name": "Trigger point", "weight_pct": 15},
            {"name": "Number of steps", "weight_pct": 15},
            {"name": "Document burden", "weight_pct": 15},
            {"name": "Completion experience", "weight_pct": 15},
            {"name": "Failure recovery and communication", "weight_pct": 15},
            {"name": "Redemption friction", "weight_pct": 25},
        ],
    },
    {
        "name": "Min/max purchase and coin packages",
        "description": "Value perception, accessibility, monetisation and package progression.",
        "weight_pct": 10,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 14, "transition_priority": 8},
        "subcriteria": [
            {"name": "Minimum purchase", "weight_pct": 20},
            {"name": "Maximum purchase", "weight_pct": 15},
            {"name": "Package ladder structure", "weight_pct": 30},
            {"name": "Value progression", "weight_pct": 20},
            {"name": "First-purchase offer", "weight_pct": 15},
        ],
    },
    {
        "name": "RTP and SC min/max",
        "description": "Product value, session economics, customer choice and prize potential.",
        "weight_pct": 10,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 14, "transition_priority": 4},
        "subcriteria": [
            {"name": "Published RTP range", "weight_pct": 30},
            {"name": "SC minimum stake", "weight_pct": 25},
            {"name": "SC maximum stake", "weight_pct": 25},
            {"name": "Prize ceiling", "weight_pct": 20},
        ],
    },
    {
        "name": "Payment options, limits and experience",
        "description": "Payment coverage and friction directly influence conversion and redemption trust.",
        "weight_pct": 9,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 11, "transition_priority": 20},
        "subcriteria": [
            {"name": "Purchase method coverage", "weight_pct": 25},
            {"name": "Redemption method coverage", "weight_pct": 25},
            {"name": "Redemption speed", "weight_pct": 25},
            {"name": "Limits and thresholds", "weight_pct": 15},
            {"name": "Failure handling", "weight_pct": 10},
        ],
    },
    {
        "name": "State availability and variation",
        "description": "Determines addressable market and operating complexity.",
        "weight_pct": 7,
        "refresh_cadence": "quarterly",
        "view_weights": {"customer_proposition": 1, "transition_priority": 14},
        "subcriteria": [
            {"name": "States available", "weight_pct": 40},
            {"name": "Excluded states", "weight_pct": 30},
            {"name": "Per-state proposition variation", "weight_pct": 30},
        ],
    },
    {
        "name": "Marketing proposition",
        "description": "Brand preference, trust, and effectiveness of acquisition spend.",
        "weight_pct": 7,
        "refresh_cadence": "weekly",
        "view_weights": {"customer_proposition": 3, "transition_priority": 0},
        "subcriteria": [
            {"name": "Trust-site presence and rating", "weight_pct": 30},
            {"name": "Advertising presence and creative", "weight_pct": 30},
            {"name": "Positioning clarity", "weight_pct": 20},
            {"name": "Affiliate and influencer footprint", "weight_pct": 20},
        ],
    },
    {
        "name": "Exclusive-game strategy",
        "description": "Differentiation, although value depends on quality and prominence.",
        "weight_pct": 6,
        "refresh_cadence": "monthly",
        "view_weights": {"customer_proposition": 6, "transition_priority": 1},
        "subcriteria": [
            {"name": "Number of exclusives", "weight_pct": 30},
            {"name": "Exclusive quality", "weight_pct": 40},
            {"name": "Prominence in lobby", "weight_pct": 30},
        ],
    },
    {
        "name": "AMOE policy and proposition",
        "description": "Compliance, transparency and trust; usually less commercially differentiating.",
        "weight_pct": 5,
        "refresh_cadence": "quarterly",
        "view_weights": {"customer_proposition": 0, "transition_priority": 2},
        "subcriteria": [
            {"name": "Visibility of AMOE route", "weight_pct": 30},
            {"name": "Ease of completion", "weight_pct": 30},
            {"name": "Value granted", "weight_pct": 25},
            {"name": "Terms clarity", "weight_pct": 15},
        ],
    },
    {
        "name": "Available P&L, accounts and financial strength",
        "description": "Competitive capacity; not a direct customer proposition.",
        "weight_pct": 4,
        "refresh_cadence": "quarterly",
        "view_weights": {"customer_proposition": 0, "transition_priority": 0},
        "subcriteria": [
            {"name": "Filed accounts availability", "weight_pct": 30},
            {"name": "Revenue scale", "weight_pct": 40},
            {"name": "Profitability signal", "weight_pct": 30},
        ],
    },
]

_SOW_SUBJECTS: list[dict[str, Any]] = [
    {
        "name": "Pulsz",
        "group_name": "YSI (in-house)",
        "url": "https://www.pulsz.com",
        "is_self": True,
    },
    {
        "name": "Pulsz Bingo",
        "group_name": "YSI (in-house)",
        "url": "https://www.pulszbingo.com",
        "is_self": True,
    },
    {
        "name": "Chumba Casino",
        "group_name": "VGW",
        "url": "https://www.chumbacasino.com",
    },
    {
        "name": "LuckyLand Slots",
        "group_name": "VGW",
        "url": "https://www.luckylandslots.com",
    },
    {
        "name": "Crown Coins Casino",
        "group_name": "Crown Coins",
        "url": "https://www.crowncoinscasino.com",
    },
    {"name": "Modo Casino", "group_name": "Modo", "url": "https://www.modo.us"},
    {"name": "WOW Vegas", "group_name": "WOW Vegas", "url": "https://www.wowvegas.com"},
    {"name": "Card Crush", "group_name": "B2S", "url": "https://www.cardcrush.com"},
    {"name": "McLuck", "group_name": "B2S", "url": "https://www.mcluck.com"},
    {"name": "Spin Blitz", "group_name": "B2S", "url": "https://www.spinblitz.com"},
    {
        "name": "Hello Millions",
        "group_name": "B2S",
        "url": "https://www.hellomillions.com",
    },
    {"name": "Jackpota", "group_name": "B2S", "url": "https://www.jackpota.com"},
    {"name": "Spree", "group_name": "B2S", "url": "https://www.spree.com"},
    {
        "name": "High 5 Casino",
        "group_name": "High 5",
        "url": "https://www.high5casino.com",
    },
]

SEED_PACKS: dict[str, dict[str, Any]] = {
    "social_casino_t1": {
        "description": (
            "Yellow Social Interactive SOW — Pulsz + Pulsz Bingo vs 12 T1 "
            "sweepstakes-casino competitors across 12 weighted dimensions."
        ),
        "dimensions": _SOW_DIMENSIONS,
        "subjects": _SOW_SUBJECTS,
    },
}


def get_pack(name: str) -> dict[str, Any] | None:
    return SEED_PACKS.get(name)


def list_packs() -> list[dict[str, str]]:
    return [
        {"name": k, "description": str(v.get("description", ""))}
        for k, v in SEED_PACKS.items()
    ]
