"""Create user_connectors table.

Revision ID: 006_user_connectors
Revises: 005_schedule_device_binding
Create Date: 2026-10-03 14:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006_user_connectors"
down_revision: Union[str, None] = "005_schedule_device_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="disconnected"),
        sa.Column("auth_type", sa.String(32), nullable=False, server_default="none"),
        sa.Column("account_identifier", sa.String(255), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_connectors_user_id", "user_connectors", ["user_id"])
    op.create_index("ix_user_connectors_connector_id", "user_connectors", ["connector_id"])
    op.create_index(
        "ix_user_connectors_user_id_connector_id",
        "user_connectors",
        ["user_id", "connector_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("user_connectors")
