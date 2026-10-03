"""Bind scheduled tasks to the NEXUS device that created them.

Revision ID: 005_schedule_device_binding
Revises: 004_scheduled_automation_upgrade
Create Date: 2026-10-03 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005_schedule_device_binding"
down_revision: Union[str, None] = "004_scheduled_automation_upgrade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_tasks",
        sa.Column("device_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE scheduled_tasks "
            "SET device_id = 'unbound', enabled = false, "
            "metadata_json = COALESCE(metadata_json, '{}'::jsonb) "
            "|| '{\"device_binding_required\": true}'::jsonb "
            "WHERE device_id IS NULL"
        )
    )
    op.alter_column("scheduled_tasks", "device_id", nullable=False)
    op.drop_index("ix_scheduled_tasks_due", table_name="scheduled_tasks")
    op.create_index(
        "ix_scheduled_tasks_due",
        "scheduled_tasks",
        ["device_id", "enabled", "next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_due", table_name="scheduled_tasks")
    op.create_index(
        "ix_scheduled_tasks_due",
        "scheduled_tasks",
        ["enabled", "next_run_at"],
        unique=False,
    )
    op.drop_column("scheduled_tasks", "device_id")
