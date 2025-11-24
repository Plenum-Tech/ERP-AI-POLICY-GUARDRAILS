from sqlalchemy import (
    Table, Column, String, Integer, DateTime, text, MetaData
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
import uuid

metadata = MetaData(schema="erp_ai")   # your existing schema

policy_rulepacks = Table(
    "policy_rulepacks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("org_id", String, nullable=False, index=True),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("rulepack", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), server_default=text("now()")),
)
