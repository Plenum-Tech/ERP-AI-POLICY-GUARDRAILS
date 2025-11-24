"""
Rule: Per-transaction cap (general, non-weekend specific)

Policy intent (PoC):
- Each category may have a per-transaction limit (e.g., Entertainment ≤ AED 500).
- On weekends, a separate weekend cap may apply (handled by weekend.py).
  This rule focuses on the general per-tx cap and avoids double-messaging
  if a weekend-specific cap exists.

Rule pack knobs:
{
  "caps": {
    "per_tx": { "Entertainment": 500 },
    "per_tx_weekend": { "Entertainment": 500 }   // optional; handled by weekend.py
  }
}

Behavior:
- Resolve category cap from caps.per_tx.
- If it's a weekend AND a weekend override exists for this category,
  skip here (weekend.py will handle).
- If amount > cap → SOFT_BLOCK with guidance; Risk flag: CAP_OVER_TX.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _msg(code: str, text: str, severity: Severity = Severity.WARNING) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["split_expense", "add_justification"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _cap_for_category(rp: Dict[str, Any], category: str) -> Optional[Decimal]:
    try:
        cap_map = ((rp.get("caps") or {}).get("per_tx") or {})
        if category in cap_map:
            return Decimal(str(cap_map[category]))
    except Exception:
        return None
    return None


def _has_weekend_override(rp: Dict[str, Any], category: str) -> bool:
    try:
        wk_map = ((rp.get("caps") or {}).get("per_tx_weekend") or {})
        return category in wk_map
    except Exception:
        return False


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    category = tx.category_code

    cap = _cap_for_category(rulepack, category)
    if cap is None:
        return None

    # If it's weekend AND a weekend override exists for this category,
    # let weekend.py handle to avoid duplicate messages.
    is_weekend = await repos.is_weekend(tx.date, (rulepack.get("weekend") or {}))
    if is_weekend and _has_weekend_override(rulepack, category):
        return None

    amount = Decimal(str(tx.amount or 0))
    if amount <= cap:
        return None

    over = amount - cap
    text = (
        f"Per-transaction cap for '{category}' is {cap:.2f}; you're over by {over:.2f}. "
        "Consider splitting the expense or adding a short justification."
    )

    return RuleOutcome(
        status_delta="SOFT_BLOCK",
        messages=[_msg("CAP_OVER_TX", text)],
        flags=[_flag("CAP_OVER_TX", f"amount={amount:.2f} > cap={cap:.2f}")],
        hard_requirements=[],
    )
