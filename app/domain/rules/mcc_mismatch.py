"""
Rule: MCC/category mismatch

Policy intent (PoC):
- If a card transaction's MCC does not align with the selected expense category,
  surface a warning and add a risk flag for Finance review.

Rule pack knobs:
{
  "mcc_rules": {
    "category_allowed_mcc": {
      "Entertainment": ["5813","7932","7929"]
    },
    "mismatch_weight": 15   # (handled by risk_weights; kept here for reference)
  }
}

Behavior:
- If tx.mcc is missing → no-op (not a card tx / MCC unavailable).
- If the category has an allowlist and MCC NOT in it:
    → WARNING message (no block) + RiskFlag MCC_MISMATCH.
- If no allowlist configured for the category → no-op (PoC-friendly).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("mcc_rules") or {}) if isinstance(rulepack, dict) else {}


def _msg(code: str, text: str) -> PolicyMessage:
    return PolicyMessage(
        severity=Severity.WARNING,
        code=code,
        text=text,
        suggested_actions=["verify_category", "add_justification"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    mcc = (tx.mcc or "").strip()
    if not mcc:
        return None  # no MCC → skip

    cfg = _cfg(rulepack)
    mapping = (cfg.get("category_allowed_mcc") or {})
    allowed = set(mapping.get(tx.category_code, []))
    if not allowed:
        return None  # no allowlist configured for this category

    if mcc not in allowed:
        allowed_str = ", ".join(sorted(allowed)) or "—"
        return RuleOutcome(
            status_delta=None,  # warn only (no block) in PoC
            messages=[
                _msg(
                    "MCC_MISMATCH",
                    f"MCC {mcc} doesn’t match the expected set for '{tx.category_code}' "
                    f"({allowed_str}). Please verify category or add justification."
                )
            ],
            flags=[_flag("MCC_MISMATCH", f"mcc={mcc}, allowed={sorted(list(allowed))}")],
            hard_requirements=[],
        )

    return None
