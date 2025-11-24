"""
Rule: Purchase Order (PO) required for PO-type projects

Policy intent (PoC):
- If a transaction belongs to a project that requires a PO (e.g., project_type == "PO"),
  submission should be blocked until a valid PO is on file.

Rule pack knobs:
{
  "project_docs": {
    "po_required_for": ["PO"]     // list of project_type values that require a PO
  }
}

Trigger:
- tx.project_type is in rulepack.project_docs.po_required_for

Behavior:
- If no PO found via repos.po_on_file(context) → HARD_BLOCK
- Message explains requirement; adds explicit HardRequirement "REQUIRE_PO"
- Risk flag: PO_MISSING
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import HardRequirement, PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("project_docs") or {}) if isinstance(rulepack, dict) else {}


def _msg(code: str, text: str, severity: Severity = Severity.ERROR) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["attach_po_reference", "contact_project_admin"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _hard(code: str, label: str) -> HardRequirement:
    return HardRequirement(code=code, label=label)


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    cfg = _cfg(rulepack)
    required_for = set(cfg.get("po_required_for") or [])
    tx = req.tx

    if not required_for or not tx.project_type:
        return None

    # Only enforce when the tx.project_type is configured to require PO
    if str(tx.project_type).upper() not in {v.upper() for v in required_for}:
        return None

    # Ask repository layer if a PO exists for this context (project/team info can be passed in req.context)
    has_po = await repos.po_on_file(req.context or {})
    if has_po:
        return None

    return RuleOutcome(
        status_delta="HARD_BLOCK",
        messages=[
            _msg(
                "PO_MISSING",
                "A valid Purchase Order is required for this project type. "
                "Please attach the PO reference or select a project with an approved PO."
            )
        ],
        flags=[_flag("PO_MISSING", "PO not found for PO-type project in current context")],
        hard_requirements=[_hard("REQUIRE_PO", "Attach valid PO reference/document")],
    )
