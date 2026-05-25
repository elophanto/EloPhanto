"""Shared email-logging helpers.

Three email tools (``send_tool``, ``reply_tool``, ``create_inbox_tool``)
all write to ``email_log`` with slightly different column shapes. This
module holds the cross-cutting concern: mirror outbound email events
into ``resource_ledger`` so the board view can count touches per
company without joining through email_log.

Only outbound rows count as touches. Inbound (incoming) and system
(inbox-creation) rows are noise for the touch metric.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 1.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def mirror_email_to_ledger(
    db: Any,
    *,
    email_log_id: int,
    direction: str,
    tool_name: str,
    recipient: str | None = None,
) -> None:
    """Append a ``type='email_sent'`` ledger row for an outbound email.

    No-op for non-outbound directions (inbound, system). Never raises —
    ledger errors are logged and swallowed; email_log is the source of
    truth, the ledger is a denormalized read model.
    """
    if direction != "outbound":
        return
    if email_log_id <= 0:
        return

    try:
        from core.company import current_company_id
        from core.ledger import LedgerEntry, ResourceLedger

        ledger = ResourceLedger(db)
        await ledger.write(
            LedgerEntry(
                company_id=current_company_id(),
                direction="out",
                type="email_sent",
                amount=1.0,
                unit="count",
                source_table="email_log",
                source_id=email_log_id,
                note=f"{tool_name}{f' → {recipient}' if recipient else ''}",
            )
        )
    except Exception as e:
        logger.debug("email ledger mirror failed: %s", e)
