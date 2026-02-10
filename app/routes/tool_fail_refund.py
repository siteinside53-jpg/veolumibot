"""Κοινό helper: όταν ένα εργαλείο αποτύχει, κάνε release hold + στείλε friendly μήνυμα.

Βάλε αυτό το αρχείο στο: app/core/tool_fail_refund.py

Χρήση μέσα στα app/api/<tool>/generate:

    from app.db import create_credit_hold, capture_credit_hold
    from app.core.tool_fail_refund import fail_and_refund

    hold = create_credit_hold(user_id, cost, reason="nanobanana_pro", provider="nanobanana_pro", idempotency_key=job_id)
    hold_id = int(hold["id"])

    try:
        provider_resp = ...
        capture_credit_hold(hold_id, reason="nanobanana_pro", provider="nanobanana_pro", provider_ref=provider_job_id)
    except Exception as e:
        await fail_and_refund(chat_id=chat_id, hold_id=hold_id, cost=float(cost), raw_error=str(e))
        raise
"""

from __future__ import annotations
from typing import Optional

from app.db import release_credit_hold
from app.core.telegram_client import tg_send_message_safe
from app.texts import map_provider_error_to_gr, tool_error_message_gr


async def fail_and_refund(
    *,
    chat_id: int,
    hold_id: Optional[int],
    cost: float,
    raw_error: str,
) -> None:
    refunded = None

    # refund (release hold) — idempotent
    if hold_id is not None:
        ok = release_credit_hold(hold_id, reason="tool_failed")
        if ok:
            refunded = float(cost)

    reason, tips = map_provider_error_to_gr(raw_error)
    msg = tool_error_message_gr(reason=reason, tips=tips, refunded=refunded)
    await tg_send_message_safe(chat_id, msg)
