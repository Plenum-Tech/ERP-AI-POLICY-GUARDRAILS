"""
Rule: Forex card usage constraints

Policy intent (PoC):
- Company forex cards may be used only for specific categories (e.g., Taxi, F&B).
- Any other usage is a policy breach and must be blocked until justified/approved.

Rule pack knobs:
{
  "forex_card": {
    "enabled": true,
    "allowed_categories": ["Taxi","F&B"]
  }
}

Behavior:
- If forex_card.enabled is false → no-op.
- If tx.payment_type != "FOREX_CARD" → no-op.
- If category NOT in allowed_categories → HARD_BLOCK + risk flag FOREX_MISUSE
  and a hard requirement to attach a manager/finance approval note.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import HardRequirement, PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("forex_card") or {}) if isinstance(rulepack, dict) else {}


def _msg(code: str, text: str, severity: Severity = Severity.ERROR) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["attach_manager_approval", "use_personal_card_and_claim"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _hard(code: str, label: str) -> HardRequirement:
    return HardRequirement(code=code, label=label)


def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    cfg = _cfg(rulepack)
    if cfg.get("enabled", True) is False:
        return None

    tx = req.tx
    if (tx.payment_type or "").upper() != "FOREX_CARD":
        return None

    allowed = set((cfg.get("allowed_categories") or []))
    if not allowed:
        # No allowlist configured → treat as pass-through in PoC
        return None

    if tx.category_code not in allowed:
        allowed_str = ", ".join(sorted(allowed)) or "—"
        return RuleOutcome(
            status_delta="HARD_BLOCK",
            messages=[
                _msg(
                    "FOREX_MISUSE",
                    f"Forex card usage is restricted to: {allowed_str}. "
                    f"Category '{tx.category_code}' is not permitted."
                )
            ],
            flags=[_flag("FOREX_MISUSE", f"Used forex card for category '{tx.category_code}' (allowed: {sorted(list(allowed))})")],
            hard_requirements=[_hard("REQUIRE_MANAGER_NOTE", "Attach Finance/Manager approval or repay and resubmit")],
        )

    return None
