"""
Rule: Potential duplicate claim

Policy intent (PoC):
- Prevent/flag accidental double-claims of the same expense.

Rule pack knobs:
{
  "duplicate_rules": {
    "window_days": 14,              # lookback window
    "same_amount_tolerance": 1.00,  # ± amount tolerance (tx currency units)
    "desc_fuzzy_threshold": 0.85,   # 0..1 (RapidFuzz token_set_ratio/100)
    "time_bucket_hours": 24         # PoC approximates with same-date bucket
  }
}

Behavior (uses repos.duplicate_suspect()):
- If suspect duplicate found within window:
    → SOFT_BLOCK with guidance to add justification or cancel
    → Risk flag: DUPLICATE
Notes:
- This PoC relies on `poc_transactions` history for lookback. Replace with your real tx table later.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rp: Dict[str, Any]) -> Dict[str, Any]:
    return (rp.get("duplicate_rules") or {}) if isinstance(rp, dict) else {}


def _msg(code: str, text: str, severity: Severity = Severity.WARNING) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["add_justification", "cancel_if_duplicate"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    cfg = _cfg(rulepack)
    if not cfg:
        return None  # no duplicate policy configured → no-op

    tx = req.tx
    suspect = await repos.duplicate_suspect(
        org_id=req.org_id,
        user_id=req.user_id,
        tx={"date": tx.date, "amount": tx.amount, "description": tx.description or ""},
        dup_rules=cfg,
    )
    if not suspect:
        return None

    return RuleOutcome(
        status_delta="SOFT_BLOCK",
        messages=[
            _msg(
                "DUPLICATE",
                "This looks similar to a recent claim (same-day/amount/description). "
                "If this is not a duplicate, add a short justification before submitting."
            )
        ],
        flags=[_flag("DUPLICATE", "Similar amount & description within lookback window")],
        hard_requirements=[],
    )
