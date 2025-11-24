"""
Rule: FX-rate and Tip outliers

Policy intent (PoC):
- Surface suspicious FX rates (vs. a simple reference) and unusually large tips.
- These are REVIEW cues, not blocks, in the PoC.

Rule pack knobs:
{
  "fx_rules": {
    "max_deviation_pct": 5.0,         # flag if |tx.fx_rate - ref|/ref > 5%
    "tip_max_pct": 20.0,              # flag if tip_amount > 20% of amount
    "reference": { "USD": 3.6725 }    # optional per-currency base; fallback map used if absent
  }
}

Behavior:
- If currency != AED and tx.fx_rate present:
    - compare with reference; if deviation exceeds → WARNING + RiskFlag FX_OUTLIER
- If tip_amount present and exceeds tip_max_pct of amount:
    - WARNING + RiskFlag TIP_OUTLIER
- No status change (PASS) in PoC.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("fx_rules") or {}) if isinstance(rulepack, dict) else {}


def _msg(code: str, text: str) -> PolicyMessage:
    return PolicyMessage(
        severity=Severity.WARNING,
        code=code,
        text=text,
        suggested_actions=["verify_rate", "add_justification", "adjust_tip_if_needed"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    cfg = _cfg(rulepack)

    messages, flags = [], []

    # FX-rate outlier?
    try:
        if await repos.fx_deviation_exceeds(tx.model_dump(), cfg):
            messages.append(_msg("FX_OUTLIER", "Applied FX rate looks off vs. reference. Please verify and add a note."))
            flags.append(_flag("FX_OUTLIER", f"currency={tx.currency}, fx_rate={tx.fx_rate}"))
    except Exception as e:
        # Non-fatal: if reference missing or parsing fails, skip silently in PoC
        pass

    # Tip outlier?
    try:
        if await repos.tip_exceeds(tx.model_dump(), cfg):
            messages.append(_msg("TIP_OUTLIER", "Tip appears above the usual policy threshold. Please justify."))
            flags.append(_flag("TIP_OUTLIER", f"amount={tx.amount}, tip={tx.tip_amount}"))
    except Exception:
        pass

    if not messages:
        return None

    return RuleOutcome(
        status_delta=None,  # warn-only in PoC
        messages=messages,
        flags=flags,
        hard_requirements=[],
    )
