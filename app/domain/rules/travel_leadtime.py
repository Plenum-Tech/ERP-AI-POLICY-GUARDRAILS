"""
Rule: Travel lead time (working days notice)

Policy intent (PoC):
- Travel should be planned with a minimum working-days notice (default 7).
- Short-notice travel is allowed only with justification/approval.

Rule pack knobs:
{
  "travel": {
    "min_notice_working_days": 7
  }
}

Inputs (PoC):
- We read the intended trip start date from `req.context["travel_start"]` (ISO date string).
  *If absent, the rule is a no-op* (keeps API lean; you can add a dedicated travel payload later).
- "Working days" use the weekend config from rule pack (default UAE Fri/Sat) and org holidays.

Behavior:
- If working-days gap between "today" (submission time) and travel_start < min_notice:
    → SOFT_BLOCK + TRAVEL_SHORT_NOTICE flag
    → Message suggests attaching client justification or manager approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Any, Dict, Optional

import pytz

from app.core.config import settings
from app.models import PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rp: Dict[str, Any]) -> Dict[str, Any]:
    return (rp.get("travel") or {}) if isinstance(rp, dict) else {}


def _msg(code: str, text: str) -> PolicyMessage:
    return PolicyMessage(
        severity=Severity.WARNING,
        code=code,
        text=text,
        suggested_actions=["attach_client_justification", "attach_manager_approval"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        return None


async def _is_working_day(d: date, weekend_days: set[str], org_id: str, repos) -> bool:
    # weekend_days are strings like "FRI","SAT"
    weekday_map = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
    if weekday_map[d.weekday()] in weekend_days:
        return False
    if await repos.is_holiday(org_id, d):
        return False
    return True


async def _working_days_between(
    start: date, end: date, weekend_days: set[str], org_id: str, repos
) -> int:
    """
    Count working days in (start, end], i.e., days strictly after start up to and including end.
    If end <= start, returns 0.
    """
    if end <= start:
        return 0
    days = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if await _is_working_day(cur, weekend_days, org_id, repos):
            days += 1
        cur += timedelta(days=1)
    return days


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    cfg = _cfg(rulepack)
    min_notice = int(cfg.get("min_notice_working_days", 7))

    travel_start_raw = (req.context or {}).get("travel_start")
    if not travel_start_raw:
        return None  # No travel context → no-op (PoC-friendly)

    travel_start = _parse_iso_date(str(travel_start_raw))
    if not travel_start:
        # Invalid date format → treat as a soft warning but do not block
        return RuleOutcome(
            status_delta=None,
            messages=[_msg("TRAVEL_DATE_INVALID", "Travel start date format is invalid; please use YYYY-MM-DD.")],
            flags=[_flag("TRAVEL_DATE_INVALID", f"value={travel_start_raw}")],
            hard_requirements=[],
        )

    # Today in service timezone (submission time)
    tz = pytz.timezone(getattr(settings, "APP_TIMEZONE", "Asia/Dubai"))
    today = datetime.now(tz).date()

    # Weekend config
    weekend_cfg = (rulepack.get("weekend") or {})
    weekend_days = set(weekend_cfg.get("days", ["FRI", "SAT"]))

    # Compute working-day gap
    gap = await _working_days_between(today, travel_start, weekend_days, req.org_id, repos)

    if gap >= min_notice:
        return None

    miss = min_notice - gap
    text = (
        f"Travel planned with only {gap} working day(s) notice; minimum required is {min_notice}. "
        f"You're short by {miss} day(s). Please attach client justification or manager approval."
    )
    return RuleOutcome(
        status_delta="SOFT_BLOCK",
        messages=[_msg("TRAVEL_SHORT_NOTICE", text)],
        flags=[_flag("TRAVEL_SHORT_NOTICE", f"gap={gap}, min={min_notice}, travel_start={travel_start.isoformat()}")],
        hard_requirements=[],
    )
