"""
Rule: PCC (Post Contract/Compliance) required before payment

Policy intent (PoC):
- Certain projects/payments must not be released until a PCC (or equivalent compliance doc) is on file.
- For the PoC, we only enforce this rule when the evaluation context indicates we are at the payment step.

Rule pack knobs:
{
  "project_docs": {
    "pcc_required_for_payment": true
  }
}

Trigger (PoC):
- req.context["stage"] in {"payment","payrun"} OR req.context["is_payment"] == True

Behavior:
- If pcc_required_for_payment is true and we're in the payment stage:
    -> call repos.pcc_on_file(project_id)  (project_id is optional; pulled from req.context.get("project_id"))
    -> if False -> HARD_BLOCK + risk flag PCC_MISSING + hard requirement REQUIRE_PCC
- Otherwise → no-op

Notes:
- repos.pcc_on_file() is a stub in PoC; wire it to your real project/compliance store later.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models import HardRequirement, PolicyMessage, RiskFlag, Severity
from app.services.policy_engine import RuleOutcome


def _cfg(rulepack: Dict[str, Any]) -> Dict[str, Any]:
    return (rulepack.get("project_docs") or {}) if isinstance(rulepack, dict) else {}


def _is_payment_stage(ctx: Dict[str, Any]) -> bool:
    if not ctx:
        return False
    stage = str(ctx.get("stage", "")).lower()
    if stage in {"payment", "payrun"}:
        return True
    if bool(ctx.get("is_payment", False)):
        return True
    return False


def _msg(code: str, text: str, severity: Severity = Severity.ERROR) -> PolicyMessage:
    return PolicyMessage(
        severity=severity,
        code=code,
        text=text,
        suggested_actions=["attach_pcc_reference", "contact_project_admin"],
    )


def _flag(code: str, reason: str) -> RiskFlag:
    return RiskFlag(code=code, reason=reason)


def _hard(code: str, label: str) -> HardRequirement:
    return HardRequirement(code=code, label=label)


async def check(req, rulepack: Dict[str, Any], repos) -> Optional[RuleOutcome]:
    cfg = _cfg(rulepack)
    if not bool(cfg.get("pcc_required_for_payment", False)):
        return None

    ctx = req.context or {}
    if not _is_payment_stage(ctx):
        return None  # only enforce at payment time

    project_id = ctx.get("project_id")  # optional
    has_pcc = await repos.pcc_on_file(project_id)
    if has_pcc:
        return None

    return RuleOutcome(
        status_delta="HARD_BLOCK",
        messages=[
            _msg(
                "PCC_MISSING",
                "Compliance (PCC) documentation is required before payment. "
                "Please attach a valid PCC reference/document."
            )
        ],
        flags=[_flag("PCC_MISSING", f"PCC not found for project_id={project_id}")],
        hard_requirements=[_hard("REQUIRE_PCC", "Attach valid PCC reference/document")],
    )
