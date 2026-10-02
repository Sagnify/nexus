"""Upgrade scheduled tasks for persistent automation execution

Revision ID: 004_scheduled_automation_upgrade
Revises: 003_scheduled_tasks
Create Date: 2026-10-02 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_scheduled_automation_upgrade'
down_revision: Union[str, None] = '003_scheduled_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add automation execution columns to scheduled_tasks
    op.add_column(
        'scheduled_tasks',
        sa.Column('normalized_intent', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}')
    )
    op.add_column(
        'scheduled_tasks',
        sa.Column('execution_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}')
    )
    op.add_column(
        'scheduled_tasks',
        sa.Column('last_run_status', sa.String(length=32), nullable=True)
    )

    # 2. Add worker claiming & artifact tracking columns to scheduled_task_runs
    op.add_column(
        'scheduled_task_runs',
        sa.Column('worker_id', sa.String(length=128), nullable=True)
    )
    op.add_column(
        'scheduled_task_runs',
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'scheduled_task_runs',
        sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]')
    )
    op.create_index(
        'ix_scheduled_task_runs_worker_id',
        'scheduled_task_runs',
        ['worker_id'],
        unique=False
    )
    op.create_index(
        'ix_scheduled_runs_status_scheduled_for',
        'scheduled_task_runs',
        ['status', 'scheduled_for'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_scheduled_runs_status_scheduled_for', table_name='scheduled_task_runs')
    op.drop_index('ix_scheduled_task_runs_worker_id', table_name='scheduled_task_runs')
    op.drop_column('scheduled_task_runs', 'artifacts')
    op.drop_column('scheduled_task_runs', 'claimed_at')
    op.drop_column('scheduled_task_runs', 'worker_id')

    op.drop_column('scheduled_tasks', 'last_run_status')
    op.drop_column('scheduled_tasks', 'execution_config')
    op.drop_column('scheduled_tasks', 'normalized_intent')
