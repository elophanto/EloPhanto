"""Company posture — maturity × objective for ABE attention + spend.

Posture is the operator-declared operating stance for a company:

- ``maturity`` gates channel breadth (extends founder-doctrine Stage 0).
- ``objective`` reshapes arbiter weights, role rotation, and spend envelopes.

Stored under ``posture:`` in ``companies/<slug>/company.yaml``. Falls back to
``strategy_inputs.maturity`` when posture is absent so existing companies keep
working. See the maturity × objective design that ships with this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VALID_MATURITY: tuple[str, ...] = (
    "pre_revenue",
    "early",
    "scaling",
    "established",
)
VALID_OBJECTIVE: tuple[str, ...] = (
    "validate",
    "growth",
    "profit",
    "balance",
)

# Intent presets the drive-business skill can propose.
INTENT_PRESETS: dict[str, tuple[str, str]] = {
    "startup_founder": ("pre_revenue", "validate"),
    "established": ("established", "balance"),
    "profitability": ("scaling", "profit"),
    "growth": ("early", "growth"),
}

_DEFAULT_MATURITY = "scaling"
_DEFAULT_OBJECTIVE = "balance"


@dataclass(slots=True, frozen=True)
class Posture:
    maturity: str = _DEFAULT_MATURITY
    objective: str = _DEFAULT_OBJECTIVE

    def label(self) -> str:
        return f"{self.maturity}/{self.objective}"

    def as_dict(self) -> dict[str, str]:
        return {"maturity": self.maturity, "objective": self.objective}


def _default_path(project_root: Path, company_id: str) -> Path:
    return project_root / "companies" / company_id / "company.yaml"


def normalize_maturity(raw: str | None) -> str:
    m = str(raw or "").strip().lower()
    return m if m in VALID_MATURITY else _DEFAULT_MATURITY


def normalize_objective(raw: str | None) -> str:
    o = str(raw or "").strip().lower()
    return o if o in VALID_OBJECTIVE else _DEFAULT_OBJECTIVE


def load_posture(
    project_root: Path,
    company_id: str,
    *,
    override_path: Path | None = None,
) -> Posture:
    """Load posture from company.yaml (fail-soft → defaults).

    Preference order for maturity:
      1. ``posture.maturity``
      2. ``strategy_inputs.maturity`` (legacy)
      3. ``scaling``
    """
    path = override_path or _default_path(project_root, company_id)
    if not path.is_file():
        return Posture()

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("posture: parse failed for %s: %s", path, e)
        return Posture()

    if not isinstance(data, dict):
        return Posture()

    raw_posture = data.get("posture")
    posture_block: dict[str, Any] = raw_posture if isinstance(raw_posture, dict) else {}
    raw_strategy = data.get("strategy_inputs")
    strategy_inputs: dict[str, Any] = (
        raw_strategy if isinstance(raw_strategy, dict) else {}
    )

    maturity_raw = posture_block.get("maturity") or strategy_inputs.get("maturity")
    objective_raw = posture_block.get("objective")

    return Posture(
        maturity=normalize_maturity(maturity_raw),
        objective=normalize_objective(objective_raw),
    )


def save_posture(
    project_root: Path,
    company_id: str,
    posture: Posture,
    *,
    override_path: Path | None = None,
) -> Path:
    """Write ``posture:`` and mirror maturity into ``strategy_inputs``.

    Creates the YAML file only if it already exists — posture requires an
    onboarded/productized company (same rule as strategy_inputs).
    """
    import yaml

    path = override_path or _default_path(project_root, company_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"companies/{company_id}/company.yaml does not exist — "
            "run company_onboard first."
        )

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ValueError(f"company.yaml parse failed: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("company.yaml top-level must be a mapping")

    doc["posture"] = posture.as_dict()

    strategy_inputs = doc.get("strategy_inputs")
    if not isinstance(strategy_inputs, dict):
        strategy_inputs = {}
    strategy_inputs["maturity"] = posture.maturity
    doc["strategy_inputs"] = strategy_inputs

    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def arbiter_weight_overrides(objective: str) -> dict[str, float]:
    """Partial ArbiterWeights overrides keyed by objective.

    ``balance`` returns empty (use config/defaults). Other objectives
    retune cost / kpi / staleness / mission so attention matches the mandate.
    """
    obj = normalize_objective(objective)
    if obj == "validate":
        return {
            "cost": 0.5,  # prefer cheap cycles
            "kpi_gap_weight": 0.25,
            "staleness_bonus": 0.3,
            "mission_weight": 0.6,
            "lens_bonus": 0.4,
        }
    if obj == "growth":
        return {
            "cost": 0.2,  # tolerate spend for acquisition
            "kpi_gap_weight": 0.55,
            "staleness_bonus": 0.45,
            "mission_weight": 0.65,
            "value": 1.1,
        }
    if obj == "profit":
        return {
            "cost": 0.55,  # heavy penalty on expensive candidates
            "kpi_gap_weight": 0.35,
            "staleness_bonus": 0.35,
            "mission_weight": 0.4,
            "lens_bonus": 0.35,
        }
    return {}


def merge_arbiter_weights(
    base: Any,
    objective: str,
) -> Any:
    """Return ``base`` with posture overrides applied (same type as base).

    Uses ``dataclasses.replace`` so every field not named in the overrides is
    carried through untouched. Rebuilding from an enumerated field list would
    silently reset any weight added to ArbiterWeights later — a wrong-but-
    plausible default is exactly the kind of tuning bug nobody notices.
    """
    overrides = arbiter_weight_overrides(objective)
    if not overrides:
        return base
    try:
        import dataclasses

        if dataclasses.is_dataclass(base) and not isinstance(base, type):
            known = {f.name for f in dataclasses.fields(base)}
            applied = {k: v for k, v in overrides.items() if k in known}
            return dataclasses.replace(base, **applied)
    except Exception as e:  # non-dataclass or frozen-field surprise
        logger.warning("posture: arbiter weight merge failed (%s) — using base", e)
        return base
    return base


def source_multipliers(objective: str) -> dict[str, float]:
    """Per-candidate-source score multipliers for an objective."""
    obj = normalize_objective(objective)
    if obj == "validate":
        return {
            "workable_checkpoint": 1.15,
            "mission_momentum": 1.0,
            "role_neglect": 0.85,
            "unproductized_company": 1.2,
            "voiceless_company": 0.9,
            "unplanned_company": 1.1,
            "blocked_strategy": 1.0,
            "buildable_blocker": 0.55,
            "dream": 0.9,
            "reflex_capability_review": 0.5,
            "reflex_mission_rebalance": 0.7,
        }
    if obj == "growth":
        return {
            "workable_checkpoint": 1.2,
            "mission_momentum": 1.15,
            "role_neglect": 1.1,
            "unproductized_company": 1.0,
            "voiceless_company": 1.15,
            "unplanned_company": 1.2,
            "blocked_strategy": 1.1,
            "buildable_blocker": 0.9,
            "dream": 0.85,
            "reflex_capability_review": 0.8,
            "reflex_mission_rebalance": 1.0,
        }
    if obj == "profit":
        return {
            "workable_checkpoint": 1.0,
            "mission_momentum": 0.9,
            "role_neglect": 1.05,
            "unproductized_company": 0.8,
            "voiceless_company": 0.85,
            "unplanned_company": 0.85,
            "blocked_strategy": 1.15,  # clear blockers that burn
            "buildable_blocker": 0.45,  # don't invent tools while burning
            "dream": 0.5,
            "reflex_capability_review": 0.6,
            "reflex_mission_rebalance": 1.1,
        }
    # balance / established default — identity
    return {}


def role_priority_weights(objective: str) -> dict[str, float]:
    """Relative priority for role_neglect candidates (1.0 = neutral)."""
    obj = normalize_objective(objective)
    if obj == "validate":
        return {
            "ceo": 1.2,
            "sales": 1.35,
            "marketing": 0.45,
            "ops": 0.55,
            "support": 0.5,
        }
    if obj == "growth":
        return {
            "ceo": 0.9,
            "sales": 1.35,
            "marketing": 1.25,
            "ops": 0.75,
            "support": 0.7,
        }
    if obj == "profit":
        return {
            "ceo": 1.1,
            "sales": 1.15,
            "marketing": 0.65,
            "ops": 1.3,
            "support": 1.25,
        }
    if obj == "balance":
        # established-leaning balance: don't starve ops/support
        return {
            "ceo": 1.0,
            "sales": 1.0,
            "marketing": 1.0,
            "ops": 1.1,
            "support": 1.1,
        }
    return {}


def spend_allowed(
    posture: Posture,
    *,
    net_usd: float | None = None,
    runway_weeks: float | None = None,
    min_runway_weeks: float = 2.0,
) -> tuple[bool, str]:
    """Whether outbound spend tools may run under this posture.

    ``validate``: deny discretionary spend (cards / transfers).
    ``profit``: deny when burning and runway is thin.
    Others: allow (entity/trust gates still apply).
    """
    obj = normalize_objective(posture.objective)
    if obj == "validate":
        return False, (
            f"posture={posture.label()}: discretionary spend blocked while "
            "objective=validate. Get a paying signal first, or "
            "company_set_posture to growth/profit/balance."
        )
    if obj == "profit":
        burning = net_usd is not None and net_usd < 0.0
        thin = runway_weeks is not None and runway_weeks < min_runway_weeks
        if burning and (thin or runway_weeks is None):
            rw = f"{runway_weeks:.1f}w" if runway_weeks is not None else "unknown"
            return False, (
                f"posture={posture.label()}: spend blocked while net is "
                f"negative (runway={rw}). Cut burn or raise "
                "company_set_posture objective away from profit."
            )
    return True, ""
