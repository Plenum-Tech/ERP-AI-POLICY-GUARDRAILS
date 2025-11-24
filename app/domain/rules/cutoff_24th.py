"""
Rule: Reimbursement submission cutoff (day 24)

Policy intent (PoC):
- Claims submitted after cutoff day (default 24) roll into the next salary cycle.
- This is informational in the PoC (no block); surfaces a friendly warning + risk flag.

Rule pack knobs:
{
  "deadlines": {
    "reimbursement_cutoff_day": 24
  }
}

Behavior:
- Determine "now" in the service timezone (Asia/Dubai by default).
- If today's day > cutoff → add WARN message and flag AFTER_CUTOFF.
- No status change (PASS) — i.e., we do NOT block submission for this rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from app.core.config import settings
from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _msg(code: str, text: str) -> PolicyMessage:
    return PolicyMessage(
        severity=Severity.WARNING,
        code=code,
        text=text,
        suggested_actions=["proceed_submit"],  # purely informational in PoC
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _cutoff(rulepack: Dict[str, Any]) -> int:
    try:
        return int(((rulepack.get("deadlines") or {}).get("reimbursement_cutoff_day", 24)))
    except Exception:
        return 24


def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    # Service-local "today" (submission time), not tx.date
    tz = pytz.timezone(getattr(settings, "APP_TIMEZONE", "Asia/Dubai"))
    today = datetime.now(tz)
    cutoff_day = _cutoff(rulepack)

    if today.day <= cutoff_day:
        return None

    # After cutoff → warn user; do not block
    return RuleOutcome(
        status_delta=None,  # informational only
        messages=[
            _msg(
                "AFTER_CUTOFF",
                f"Submitted after cutoff day {cutoff_day}. This claim will be processed in the next cycle."
            )
        ],
        flags=[_flag("AFTER_CUTOFF", f"Submitted on {today.date().isoformat()} (>{cutoff_day})")],
        hard_requirements=[],
    )
