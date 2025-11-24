"""
Rule: Monthly budget (MTD) per category

Policy intent (PoC):
- Each category can have a monthly spending limit per org (optionally per month in DB).
- When (MTD_spend + current_tx) > limit → warn the user and flag risk.

Rulepack knobs (two sources for limit; DB takes precedence):
1) DB table budgets_monthly (org_id, category_code, month_start, amount)  <-- primary
2) Rule pack fallback:
{
  "budgets": {
    "monthly_limits": { "Entertainment": 1500 }
  }
}

Behavior:
- If no limit found (DB or rulepack) → no-op.
- Compute MTD from poc_transactions (PoC) and add current tx amount.
- If over limit → SOFT_BLOCK (PoC choice; change to HARD if you want),
  message explains remaining/overage, risk flag BUDGET_OVER.

Implementation notes:
- All money values are converted to Decimal for safe arithmetic.
- If repos.resolve_budget / repos.mtd_spend are not implemented yet,
  this rule falls back gracefully (no RULE_ERROR).
"""

from __future__ import annotations

import inspect
from decimal import Decimal, InvalidOperation
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


def _to_decimal(value: Any) -> Optional[Decimal]:
    """
    Safely convert arbitrary numeric-ish value to Decimal.
    Returns None if conversion fails.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


async def _resolve_limit(
    org_id: str,
    category: str,
    tx_date,
    rulepack: Dict[str, Any],
    repos: Any,
) -> Optional[Decimal]:
    """
    Resolve the monthly limit for (org_id, category, month).

    Priority:
      1) DB via repos.resolve_budget(org_id, category, tx_date)
      2) rulepack.budgets.monthly_limits[category]

    Returns Decimal or None if no usable limit.
    """
    limit_db: Optional[Decimal] = None

    # --- DB-backed limit (if helper exists) ---
    if hasattr(repos, "resolve_budget"):
        try:
            res = repos.resolve_budget(org_id, category, tx_date)
            if inspect.isawaitable(res):
                res = await res
            limit_db = _to_decimal(res)
        except Exception:
            # For PoC: swallow and fall back to config
            limit_db = None

    # --- Rulepack fallback ---
    budgets_cfg = (rulepack.get("budgets") or {})
    monthly_limits = (budgets_cfg.get("monthly_limits") or {})
    limit_cfg = _to_decimal(monthly_limits.get(category))

    # DB value wins if present and valid
    return limit_db if limit_db is not None else limit_cfg


async def _get_mtd_spend(
    org_id: str,
    user_id: str,
    category: str,
    tx_date,
    repos: Any,
) -> Decimal:
    """
    Get month-to-date spend for this (org, user, category, month).

    If repos.mtd_spend is not implemented or fails, returns Decimal('0').
    Expected (but not enforced) signature if implemented:

        async def mtd_spend(org_id: str, user_id: str, category: str, tx_date: date) -> Decimal | float | None
    """
    if not tx_date:
        return Decimal("0")

    if not hasattr(repos, "mtd_spend"):
        return Decimal("0")

    try:
        res = repos.mtd_spend(org_id, user_id, category, tx_date)
        if inspect.isawaitable(res):
            res = await res
        dec = _to_decimal(res)
        return dec if dec is not None else Decimal("0")
    except Exception:
        # For PoC: if MTD calculation fails, treat as 0 and don't crash rule
        return Decimal("0")


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    tx = req.tx
    org_id, user_id = req.org_id, req.user_id
    category = tx.category_code

    # If we somehow don't have a date, we can't do MTD logic → no-op
    if not getattr(tx, "date", None):
        return None

    # 1) Resolve monthly limit (DB first, then rulepack fallback)
    limit = await _resolve_limit(
        org_id=org_id,
        category=category,
        tx_date=tx.date,
        rulepack=rulepack,
        repos=repos,
    )
    if limit is None:
        # no limit configured → pass-through
        return None

    # 2) Compute current MTD spend (existing tx) and add current amount
    current_mtd = await _get_mtd_spend(
        org_id=org_id,
        user_id=user_id,
        category=category,
        tx_date=tx.date,
        repos=repos,
    )

    amount = _to_decimal(tx.amount)
    if amount is None:
        # if amount is weird, let some other rule handle it; skip budget check
        return None

    projected = current_mtd + amount

    if projected <= limit:
        # within budget → no outcome
        return None

    over = projected - limit
    remaining = limit - current_mtd if limit > current_mtd else Decimal("0.00")

    text = (
        f"Monthly budget for '{category}' is {limit:.2f}. "
        f"Current MTD: {current_mtd:.2f}. This expense {amount:.2f} "
        f"would exceed the limit by {over:.2f}. "
        f"Remaining before this tx: {remaining:.2f}."
    )

    return RuleOutcome(
        status_delta="SOFT_BLOCK",  # PoC choice; flip to HARD_BLOCK if you want stricter behavior
        messages=[_msg("BUDGET_OVER", text)],
        flags=[_flag("BUDGET_OVER", f"MTD {current_mtd:.2f} + tx {amount:.2f} > limit {limit:.2f}")],
        hard_requirements=[],
    )
