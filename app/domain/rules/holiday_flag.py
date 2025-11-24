"""
Rule: Public holiday awareness

Policy intent (PoC):
- Surface when a transaction occurs on an org-designated public holiday.
- Default behavior is informational FLAG (no block), but can be escalated via rule pack.

Rule pack knobs (optional):
{
  "holidays": {
    "policy": "flag"        // "flag" | "soft_block" | "hard_block"
  }
}

Behavior:
- Look up org_holidays for tx.date.
- If holiday:
  - Always add RiskFlag HOLIDAY_SPEND.
  - Message severity & status_delta follow the configured policy (default: flag/info).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _policy(rulepack: Dict[str, Any]) -> str:
    try:
        return str(((rulepack.get("holidays") or {}).get("policy") or "flag")).lower()
    except Exception:
        return "flag"


def _msg(code: str, text: str, severity: Severity) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["add_justification"],  # harmless default; UI can ignore for pure flag mode
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    is_hol = await repos.is_holiday(req.org_id, tx.date)
    if not is_hol:
        return None

    pol = _policy(rulepack)
    if pol == "hard_block":
        status_delta = "HARD_BLOCK"
        severity = Severity.ERROR
    elif pol == "soft_block":
        status_delta = "SOFT_BLOCK"
        severity = Severity.WARNING
    else:
        status_delta = None
        severity = Severity.INFO

    return RuleOutcome(
        status_delta=status_delta,
        messages=[_msg("HOLIDAY_SPEND", f"{tx.date.isoformat()} is an official holiday.", severity)],
        flags=[_flag("HOLIDAY_SPEND", f"Holiday spend on {tx.date.isoformat()}")],
        hard_requirements=[],
    )
