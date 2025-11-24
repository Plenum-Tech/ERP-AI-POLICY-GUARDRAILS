"""
Rule: Receipt/Invoice evidence required

Policy intent (PoC):
- Every expense must include at least one valid receipt/invoice attachment.
- Configurable via rule pack, but defaults to "required for all" if not present.

Rule pack knobs (optional):
{
  "receipts": {
    "enabled": true,
    "required_for_all": true,
    "min_count": 1,
    "required_for_categories": ["Entertainment","Taxi"]   # optional allowlist (used only when required_for_all=false)
  }
}

Behavior:
- If receipts.enabled is false → no-op.
- If required_for_all=true → require >= min_count attachments.
- Else → require attachments only for categories in required_for_categories.
- Outcome: HARD_BLOCK with a clear message and a concrete HardRequirement.
- Risk flag: MISSING_RECEIPT
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import HardRequirement, PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("receipts") or {}) if isinstance(rulepack, dict) else {}


def _msg(code: str, text: str, severity: Severity = Severity.ERROR) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["attach_receipt"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _hard(code: str, label: str) -> HardRequirement:
    return HardRequirement(code=code, label=label)


def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    cfg = _cfg(rulepack)

    if cfg.get("enabled", True) is False:
        return None

    required_for_all = bool(cfg.get("required_for_all", True))
    required_list = set((cfg.get("required_for_categories") or []))

    needs_receipt = required_for_all or (tx.category_code in required_list)
    if not needs_receipt:
        return None

    min_count = int(cfg.get("min_count", 1))
    attachments = tx.attachments or []

    if len(attachments) >= min_count:
        return None

    # Not enough evidence → HARD block + risk flag + explicit requirement
    return RuleOutcome(
        status_delta="HARD_BLOCK",
        messages=[
            _msg(
                "MISSING_RECEIPT",
                f"Receipt/invoice is required (min {min_count}). Please attach a valid document."
            )
        ],
        flags=[_flag("MISSING_RECEIPT", f"No receipt attached; required min={min_count}")],
        hard_requirements=[_hard("REQUIRE_RECEIPT", "Attach valid receipt/invoice")],
    )
