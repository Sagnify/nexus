"""Add scheduled task tables: scheduled_tasks and scheduled_task_runs

Revision ID: 003_scheduled_tasks
Revises: 002_skill_learning_tables
Create Date: 2026-10-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_scheduled_tasks'
down_revision: Union[str, None] = '002_skill_learning_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Scheduled Tasks Table
    op.create_table(
        'scheduled_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('task_type', sa.String(length=32), nullable=False, server_default='reminder'),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('schedule_type', sa.String(length=32), nullable=False, server_default='one_time'),
        sa.Column('schedule_definition', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('missed_policy', sa.String(length=32), nullable=False, server_default='skip'),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_scheduled_tasks_user_id', 'scheduled_tasks', ['user_id'], unique=False)
    op.create_index('ix_scheduled_tasks_task_type', 'scheduled_tasks', ['task_type'], unique=False)
    op.create_index('ix_scheduled_tasks_schedule_type', 'scheduled_tasks', ['schedule_type'], unique=False)
    op.create_index('ix_scheduled_tasks_enabled', 'scheduled_tasks', ['enabled'], unique=False)
    op.create_index('ix_scheduled_tasks_next_run_at', 'scheduled_tasks', ['next_run_at'], unique=False)
    op.create_index('ix_scheduled_tasks_user_enabled_next', 'scheduled_tasks', ['user_id', 'enabled', 'next_run_at'], unique=False)
    op.create_index('ix_scheduled_tasks_due', 'scheduled_tasks', ['enabled', 'next_run_at'], unique=False)

    # 2. Scheduled Task Runs Table
    op.create_table(
        'scheduled_task_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scheduled_task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scheduled_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('execution_id', sa.String(length=128), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_scheduled_task_runs_scheduled_task_id', 'scheduled_task_runs', ['scheduled_task_id'], unique=False)
    op.create_index('ix_scheduled_task_runs_user_id', 'scheduled_task_runs', ['user_id'], unique=False)
    op.create_index('ix_scheduled_task_runs_scheduled_for', 'scheduled_task_runs', ['scheduled_for'], unique=False)
    op.create_index('ix_scheduled_task_runs_status', 'scheduled_task_runs', ['status'], unique=False)
    op.create_index('ix_scheduled_task_runs_execution_id', 'scheduled_task_runs', ['execution_id'], unique=False)
    op.create_index('ix_scheduled_runs_task_time_unique', 'scheduled_task_runs', ['scheduled_task_id', 'scheduled_for'], unique=True)
    op.create_index('ix_scheduled_runs_user_status', 'scheduled_task_runs', ['user_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_table('scheduled_task_runs')
    op.drop_table('scheduled_tasks')

