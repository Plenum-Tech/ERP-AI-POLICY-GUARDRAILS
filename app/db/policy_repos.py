from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import select, update, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_policy import policy_rulepacks
from app.utils import is_weekend
from app.core.logger import logger


class DBPolicyRepos:
    """
    Dynamic, DB-backed rulepack repository.

    Responsibilities:
    - load_rulepack(org_id)
    - save_rulepack(org_id, rulepack)
    - audit_stub()
    - helpers:
        * is_weekend(tx_date, weekend_cfg)
        * is_holiday(tx_date, rulepack)
        * resolve_budget(org_id, category_code, tx_date)
        * mtd_spend(org_id, user_id, category_code, tx_date)

    Schema (policy_rulepacks):
      org_id (PK) | version | rulepack(JSONB) | updated_at
    """

    def __init__(self, db: AsyncSession):
        # AsyncSession is injected per-request
        self.db = db

    # ----------------------------------------------------------------------
    # Load rulepack
    # ----------------------------------------------------------------------
    async def load_rulepack(self, org_id: str) -> Dict[str, Any]:
        """
        Load the rulepack for this organization.

        If not found → return a safe minimal default.
        """
        try:
            stmt = select(policy_rulepacks.c.rulepack).where(
                policy_rulepacks.c.org_id == org_id
            )
            res = await self.db.execute(stmt)
            rp = res.scalar_one_or_none()

            if rp is None:
                logger.warning(
                    f"[policy] No rulepack found for org='{org_id}'. Using default."
                )
                return self.default_rulepack()

            logger.info(f"[policy] Loaded rulepack for org='{org_id}'.")
            return rp

        except Exception as e:
            logger.error(f"[policy] ERROR loading rulepack for org='{org_id}': {e}")
            return self.default_rulepack()

    # ----------------------------------------------------------------------
    # Save / update rulepack
    # ----------------------------------------------------------------------
    async def save_rulepack(
        self, org_id: str, rulepack: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Insert or update an org rulepack.
        - Auto-increments version if updating.
        - Returns the saved rulepack JSON.
        """
        try:
            stmt = select(policy_rulepacks).where(policy_rulepacks.c.org_id == org_id)
            res = await self.db.execute(stmt)
            row = res.first()

            # -----------------------
            # UPDATE
            # -----------------------
            if row:
                new_version = (row.version or 0) + 1

                upd_stmt = (
                    update(policy_rulepacks)
                    .where(policy_rulepacks.c.org_id == org_id)
                    .values(
                        rulepack=rulepack,
                        version=new_version,
                        updated_at=text("NOW()"),
                    )
                    .returning(policy_rulepacks.c.rulepack)
                )

                updated = await self.db.execute(upd_stmt)
                await self.db.commit()

                logger.info(
                    f"[policy] Updated rulepack org={org_id} → version={new_version}"
                )
                return updated.scalar_one()

            # -----------------------
            # INSERT
            # -----------------------
            ins_stmt = (
                insert(policy_rulepacks)
                .values(
                    org_id=org_id,
                    rulepack=rulepack,
                    version=1,
                )
                .returning(policy_rulepacks.c.rulepack)
            )

            created = await self.db.execute(ins_stmt)
            await self.db.commit()

            logger.info(f"[policy] Created new rulepack org={org_id} → version=1")
            return created.scalar_one()

        except Exception as e:
            logger.error(f"[policy] save_rulepack failed for org={org_id}: {e}")
            raise

    # ----------------------------------------------------------------------
    # Audit stub
    # ----------------------------------------------------------------------
    async def audit_stub(self, **kwargs):
        """
        Placeholder for future audit logging.
        Will store:
          - who
          - what rule triggered
          - status
          - messages
          - risk score
          - timestamp
        """
        # TODO: Implement audit persistence table
        return None

    # ----------------------------------------------------------------------
    # Weekend helper
    # ----------------------------------------------------------------------
    async def is_weekend(self, tx_date: date, weekend_cfg: Dict[str, Any]) -> bool:
        """
        Shared utility helper used by weekend rules.
        Delegates to app.utils.is_weekend().
        """
        try:
            return is_weekend(tx_date, weekend_cfg)
        except Exception as e:
            logger.error(f"[policy] is_weekend failed: {e}")
            return False

    # ----------------------------------------------------------------------
    # Holiday helper (used by holiday_flag rule)
    # ----------------------------------------------------------------------
    async def is_holiday(self, tx_date: date, rulepack: Dict[str, Any]) -> bool:
        """
        Simple holiday check based on rulepack['holiday_dates'].

        - tx_date: datetime.date (from TxInput.date)
        - rulepack: full org rulepack JSON

        Returns True if tx_date.isoformat() is listed in holiday_dates.
        """
        try:
            if isinstance(tx_date, datetime):
                d_str = tx_date.date().isoformat()
            elif isinstance(tx_date, date):
                d_str = tx_date.isoformat()
            else:
                return False

            if not isinstance(rulepack, dict):
                return False

            holiday_dates = (rulepack.get("holiday_dates") or []) or []
            if not isinstance(holiday_dates, list):
                return False

            return d_str in holiday_dates

        except Exception as e:
            logger.error(f"[policy] is_holiday failed: {e}")
            return False

    # ----------------------------------------------------------------------
    # Monthly budget helper (used by monthly_budget rule)
    # ----------------------------------------------------------------------
    async def resolve_budget(
        self,
        org_id: str,
        category_code: str,
        tx_date: date,
    ) -> Optional[Decimal]:
        """
        Resolve monthly budget limit for a transaction (DB-first).

        Current PoC:
        - No budgets table yet → always returns None,
          so monthly_budget rule falls back to rulepack.budgets.monthly_limits
          or treats it as "no limit".
        - Signature matches monthly_budget.check(...) usage.

        When you wire a budgets_monthly table, implement:
          SELECT limit FROM budgets_monthly
          WHERE org_id = ... AND category_code = ... AND month_start = ...
        """
        try:
            # TODO: Implement DB lookup here later.
            return None
        except Exception as e:
            logger.error(f"[policy] resolve_budget failed for org={org_id}: {e}")
            return None

    # ----------------------------------------------------------------------
    # MTD spend helper (used by monthly_budget rule)
    # ----------------------------------------------------------------------
    async def mtd_spend(
        self,
        org_id: str,
        user_id: str,
        category_code: str,
        tx_date: date,
    ) -> Decimal:
        """
        Month-to-date spend helper for the monthly_budget rule.

        Current PoC:
        - Returns Decimal('0.00') so rules can run without a tx history table.
        - monthly_budget then effectively compares just this tx against the limit.

        Later:
        - Sum from an erp_ai.<expenses> / tx_history table where:
            org_id, user_id, category_code,
            and date in same calendar month as tx_date.
        """
        try:
            # TODO: Implement real MTD aggregation later.
            return Decimal("0.00")
        except Exception as e:
            logger.error(f"[policy] mtd_spend failed for org={org_id}: {e}")
            return Decimal("0.00")

    # ----------------------------------------------------------------------
    # Default fallback rulepack
    # ----------------------------------------------------------------------
    def default_rulepack(self) -> Dict[str, Any]:
        """
        Fallback rulepack when no custom rulepack is uploaded.

        Safe minimal behaviour:
        - Basic required fields
        - Basic weekend detection (Fri/Sat)
        - No advanced caps, FX, MCC, budgets unless configured later
        """
        return {
            "required_fields": ["date", "amount", "currency", "category_code"],

            "holidays": {"policy": "flag"},
            "holiday_dates": [],

            "weekend": {
                "enabled": True,
                "days": ["FRI", "SAT"],
                "require_approval_for": [],
            },

            "caps": {
                "per_tx": {},
                "per_tx_weekend": {},
            },

            "budgets": {
                "monthly_limits": {},
            },

            "mcc_rules": {
                "category_allowed_mcc": {},
            },

            "fx_rules": {
                "max_deviation_pct": 5.0,
                "tip_max_pct": 20.0,
            },

            "forex_card": {
                "enabled": False,
                "allowed_categories": [],
            },

            "travel": {
                "min_notice_working_days": 7,
                "upgrades_require_approval": False,
            },

            "project_docs": {
                "po_required_for": [],
                "pcc_required_for_payment": False,
            },

            "receipts": {
                "enabled": True,
                "min_count": 1,
                "hard_block": True,
            },

            "risk_weights": {},
        }
