"""Product config loader for ABE companies.

Each company optionally has a ``companies/<slug>/company.yaml`` file
declaring what it sells, how it prices, what channels it operates on,
and what its KPIs are. The dream phase reads this to anchor goal
ideation in a real business; the arbiter reads the KPIs (via the role
manager and ledger) to bias role rotation toward gaps.

**Empty `what_we_sell` is the navel-gazing risk reborn.** A company
with no declared product is a goal generator for "Self-Perception
Diff Reports" — exactly what we filtered out of the dream prompt. The
loader returns ``None`` when the field is empty, and the dream phase
silently skips the PRODUCT block in that case. The CLI surfaces the
missing-product state so the operator notices.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Product:
    name: str
    what_we_sell: str
    price: dict[str, Any] | None = None
    fulfillment: str = ""
    channels: list[str] = field(default_factory=list)
    wallet: dict[str, str] | None = None
    kpis: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""


def _default_path(project_root: Path, company_id: str) -> Path:
    """Convention: companies/<slug>/company.yaml under project root.

    Centralized so tests + CLI + loader all agree on the location.
    """
    return project_root / "companies" / company_id / "company.yaml"


def load_product(
    project_root: Path,
    company_id: str,
    *,
    override_path: Path | None = None,
) -> Product | None:
    """Load a company's product YAML.

    Returns ``None`` when any of:
      - The file does not exist.
      - The YAML fails to parse.
      - ``what_we_sell`` is missing, empty, or whitespace-only
        (navel-gazing guard).
      - The top-level YAML is not a mapping.

    Never raises. Logs warnings on parse failures; logs at debug for
    missing files (the common case for not-yet-productized companies).
    """
    path = override_path or _default_path(project_root, company_id)
    if not path.is_file():
        logger.debug("product: no yaml at %s", path)
        return None

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("product yaml %s parse failed: %s", path, e)
        return None

    if not isinstance(data, dict):
        logger.warning("product yaml %s: top-level must be a mapping", path)
        return None

    what_we_sell = str(data.get("what_we_sell") or "").strip()
    if not what_we_sell:
        logger.debug(
            "product yaml %s: empty what_we_sell — treating as unproductized",
            path,
        )
        return None

    return Product(
        name=str(data.get("name") or company_id),
        what_we_sell=what_we_sell,
        price=data.get("price") if isinstance(data.get("price"), dict) else None,
        fulfillment=str(data.get("fulfillment") or ""),
        channels=list(data.get("channels") or []),
        wallet=data.get("wallet") if isinstance(data.get("wallet"), dict) else None,
        kpis=list(data.get("kpis") or []),
        source_path=str(path),
    )
