"""Add skill learning tables: skills, skill_versions, and skill_executions

Revision ID: 002_skill_learning_tables
Revises: 001_initial_schema
Create Date: 2026-09-27 02:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_skill_learning_tables'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Skills Table
    op.create_table(
        'skills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=False, server_default='general'),
        sa.Column('environment', sa.String(length=32), nullable=False, server_default='mixed'),
        sa.Column('trigger_phrases', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('parameters_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_draft', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('health_status', sa.String(length=32), nullable=False, server_default='healthy'),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('recovery_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('selector_failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('verification_failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_skills_user_id', 'skills', ['user_id'], unique=False)
    op.create_index('ix_skills_category', 'skills', ['category'], unique=False)
    op.create_index('ix_skills_is_active', 'skills', ['is_active'], unique=False)
    op.create_index('ix_skills_user_active_health', 'skills', ['user_id', 'is_active', 'health_status'], unique=False)
    op.create_index('ix_skills_user_name_unique', 'skills', ['user_id', 'name'], unique=True)

    # 2. Skill Versions Table
    op.create_table(
        'skill_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('skill_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('steps_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('preconditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('postconditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('change_summary', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_skill_versions_skill_id', 'skill_versions', ['skill_id'], unique=False)
    op.create_index('ix_skill_version_unique', 'skill_versions', ['skill_id', 'version_number'], unique=True)

    # 3. Skill Executions Table
    op.create_table(
        'skill_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('skill_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('skills.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('parameters_used', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('step_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('recovery_attempts', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('failed_step_index', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_skill_executions_skill_id', 'skill_executions', ['skill_id'], unique=False)
    op.create_index('ix_skill_executions_user_id', 'skill_executions', ['user_id'], unique=False)
    op.create_index('ix_skill_executions_task_id', 'skill_executions', ['task_id'], unique=False)
    op.create_index('ix_skill_executions_user_skill', 'skill_executions', ['user_id', 'skill_id', 'executed_at'], unique=False)


def downgrade() -> None:
    op.drop_table('skill_executions')
    op.drop_table('skill_versions')
    op.drop_table('skills')
