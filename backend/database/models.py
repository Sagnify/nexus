"""
SQLAlchemy 2.0 Declarative Models for NEXUS.
Covers Users, Conversations, Messages, Tasks, and Structured Task Events.
"""
from __future__ import annotations
import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from backend.database.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    display_name = Column(String(255), nullable=True)
    profile_image_url = Column(String(1024), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    task_events = relationship("TaskEvent", back_populates="user", cascade="all, delete-orphan")
    skills = relationship("Skill", back_populates="user", cascade="all, delete-orphan")
    skill_executions = relationship("SkillExecution", back_populates="user", cascade="all, delete-orphan")
    scheduled_tasks = relationship("ScheduledTask", back_populates="user", cascade="all, delete-orphan")
    scheduled_task_runs = relationship("ScheduledTaskRun", back_populates="user", cascade="all, delete-orphan")
    connectors = relationship("UserConnector", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "firebase_uid": self.firebase_uid,
            "email": self.email,
            "display_name": self.display_name,
            "profile_image_url": self.profile_image_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False, default="New Conversation")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    metadata_json = Column(JSONB, nullable=True, default=dict)

    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="conversation")

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata_json or {},
        }


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)  # "user", "assistant", "system", "tool"
    content = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_json = Column(JSONB, nullable=True, default=dict)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "user_id": str(self.user_id),
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata_json or {},
        }


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id_str = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)

    task_type = Column(String(64), nullable=False, default="general", index=True)
    user_prompt = Column(Text, nullable=False)
    goal = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, running, completed, failed, cancelled
    model_used = Column(String(128), nullable=True)
    step_count = Column(Integer, default=0)

    final_response = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    metadata_json = Column(JSONB, nullable=True, default=dict)

    # Relationships
    user = relationship("User", back_populates="tasks")
    conversation = relationship("Conversation", back_populates="tasks")
    events = relationship("TaskEvent", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tasks_user_created", "user_id", "created_at"),
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_user_category", "user_id", "task_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "task_id": self.task_id_str,
            "user_id": str(self.user_id),
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "task_type": self.task_type,
            "user_prompt": self.user_prompt,
            "goal": self.goal,
            "status": self.status,
            "model_used": self.model_used,
            "step_count": self.step_count,
            "final_response": self.final_response,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata_json or {},
        }


class TaskEvent(Base):
    __tablename__ = "task_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    event_type = Column(String(64), nullable=False, index=True)  # task_created, tool_selected, tool_executed, task_completed, etc.
    tool_name = Column(String(64), nullable=True, index=True)
    application = Column(String(64), nullable=True, index=True)  # Chrome, Word, Excel, Shell, etc.
    status = Column(String(32), nullable=True, default="success")  # success, failed, warning
    duration_ms = Column(Integer, nullable=True)

    metadata_json = Column(JSONB, nullable=True, default=dict)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    task = relationship("Task", back_populates="events")
    user = relationship("User", back_populates="task_events")

    __table_args__ = (
        Index("ix_task_events_user_time", "user_id", "timestamp"),
        Index("ix_task_events_user_tool", "user_id", "tool_name"),
        Index("ix_task_events_user_app", "user_id", "application"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "task_id": str(self.task_id),
            "user_id": str(self.user_id),
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "application": self.application,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata_json or {},
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Skill(Base):
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, default="general", index=True)
    environment = Column(String(32), nullable=False, default="mixed")  # "browser" | "desktop" | "mixed"

    trigger_phrases = Column(JSONB, nullable=False, default=list)  # ["download monthly invoices", "get stripe billing"]
    parameters_schema = Column(JSONB, nullable=False, default=list)  # [{"name": "billing_month", "type": "string", "required": True}]

    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_draft = Column(Boolean, default=False, nullable=False)
    current_version = Column(Integer, default=1, nullable=False)

    # Health & Reliability Metrics
    health_status = Column(String(32), default="healthy", nullable=False)  # "healthy" | "degraded" | "suspended"
    consecutive_failures = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    recovery_count = Column(Integer, default=0, nullable=False)
    selector_failure_count = Column(Integer, default=0, nullable=False)
    verification_failure_count = Column(Integer, default=0, nullable=False)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)
    last_failed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="skills")
    versions = relationship(
        "SkillVersion",
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="desc(SkillVersion.version_number)",
    )
    executions = relationship("SkillExecution", back_populates="skill", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_skills_user_active_health", "user_id", "is_active", "health_status"),
        Index("ix_skills_user_name_unique", "user_id", "name", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "environment": self.environment,
            "trigger_phrases": self.trigger_phrases or [],
            "parameters_schema": self.parameters_schema or [],
            "is_active": self.is_active,
            "is_draft": self.is_draft,
            "current_version": self.current_version,
            "health_status": self.health_status,
            "consecutive_failures": self.consecutive_failures,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "recovery_count": self.recovery_count,
            "selector_failure_count": self.selector_failure_count,
            "verification_failure_count": self.verification_failure_count,
            "last_executed_at": self.last_executed_at.isoformat() if self.last_executed_at else None,
            "last_failed_at": self.last_failed_at.isoformat() if self.last_failed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SkillVersion(Base):
    __tablename__ = "skill_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)

    steps_json = Column(JSONB, nullable=False)  # List of validated SemanticAction objects
    preconditions = Column(JSONB, nullable=False, default=list)  # Initial environment checks
    postconditions = Column(JSONB, nullable=False, default=list)  # Final workflow success checks
    change_summary = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    skill = relationship("Skill", back_populates="versions")

    __table_args__ = (
        Index("ix_skill_version_unique", "skill_id", "version_number", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "skill_id": str(self.skill_id),
            "version_number": self.version_number,
            "steps": self.steps_json or [],
            "preconditions": self.preconditions or [],
            "postconditions": self.postconditions or [],
            "change_summary": self.change_summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SkillExecution(Base):
    __tablename__ = "skill_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String(32), nullable=False)  # "completed" | "failed" | "recovered"
    parameters_used = Column(JSONB, nullable=False, default=dict)
    step_results = Column(JSONB, nullable=False, default=list)
    recovery_attempts = Column(JSONB, nullable=False, default=list)
    error_message = Column(Text, nullable=True)
    failed_step_index = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    executed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    skill = relationship("Skill", back_populates="executions")
    user = relationship("User", back_populates="skill_executions")

    __table_args__ = (
        Index("ix_skill_executions_user_skill", "user_id", "skill_id", "executed_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "skill_id": str(self.skill_id),
            "version_number": self.version_number,
            "user_id": str(self.user_id),
            "task_id": str(self.task_id) if self.task_id else None,
            "status": self.status,
            "parameters_used": self.parameters_used or {},
            "step_results": self.step_results or [],
            "recovery_attempts": self.recovery_attempts or [],
            "error_message": self.error_message,
            "failed_step_index": self.failed_step_index,
            "duration_ms": self.duration_ms,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(64), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String(32), nullable=False, default="reminder", index=True)  # "reminder" | "automation"
    prompt = Column(Text, nullable=False)
    schedule_type = Column(String(32), nullable=False, default="one_time", index=True)  # "one_time" | "recurring"

    # Normalized schedule specification, e.g.:
    # {"frequency": "daily", "time": "09:00"} or {"frequency": "weekly", "days": ["monday"], "time": "10:00"}
    schedule_definition = Column(JSONB, nullable=False, default=dict)
    timezone = Column(String(64), nullable=False, default="UTC")

    enabled = Column(Boolean, default=True, nullable=False, index=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    total_runs = Column(Integer, default=0, nullable=False)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    missed_policy = Column(String(32), default="skip", nullable=False)  # "skip" | "run_once"

    normalized_intent = Column(JSONB, nullable=True, default=dict)
    execution_config = Column(JSONB, nullable=True, default=dict)
    last_run_status = Column(String(32), nullable=True)

    metadata_json = Column(JSONB, nullable=True, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="scheduled_tasks")
    runs = relationship(
        "ScheduledTaskRun",
        back_populates="scheduled_task",
        cascade="all, delete-orphan",
        order_by="desc(ScheduledTaskRun.scheduled_for)",
    )

    __table_args__ = (
        Index("ix_scheduled_tasks_user_enabled_next", "user_id", "enabled", "next_run_at"),
        Index("ix_scheduled_tasks_due", "device_id", "enabled", "next_run_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "device_id": self.device_id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type,
            "prompt": self.prompt,
            "schedule_type": self.schedule_type,
            "schedule_definition": self.schedule_definition or {},
            "timezone": self.timezone,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_run_status": self.last_run_status,
            "total_runs": self.total_runs,
            "consecutive_failures": self.consecutive_failures,
            "missed_policy": self.missed_policy,
            "normalized_intent": self.normalized_intent or {},
            "execution_config": self.execution_config or {},
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ScheduledTaskRun(Base):
    __tablename__ = "scheduled_task_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scheduled_task_id = Column(UUID(as_uuid=True), ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    scheduled_for = Column(DateTime(timezone=True), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, running, completed, failed, cancelled, skipped, blocked
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    execution_id = Column(String(128), nullable=True, index=True)

    worker_id = Column(String(128), nullable=True, index=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    artifacts = Column(JSONB, nullable=True, default=list)

    metadata_json = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    scheduled_task = relationship("ScheduledTask", back_populates="runs")
    user = relationship("User", back_populates="scheduled_task_runs")

    __table_args__ = (
        Index("ix_scheduled_runs_task_time_unique", "scheduled_task_id", "scheduled_for", unique=True),
        Index("ix_scheduled_runs_user_status", "user_id", "status"),
        Index("ix_scheduled_runs_status_scheduled_for", "status", "scheduled_for"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "scheduled_task_id": str(self.scheduled_task_id),
            "user_id": str(self.user_id),
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "execution_id": self.execution_id,
            "worker_id": self.worker_id,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "artifacts": self.artifacts or [],
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserConnector(Base):
    __tablename__ = "user_connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="disconnected")
    auth_type = Column(String(32), nullable=False, default="none")
    account_identifier = Column(String(255), nullable=True)
    metadata_json = Column(JSONB, nullable=True, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="connectors")

    __table_args__ = (
        Index("ix_user_connectors_user_id_connector_id", "user_id", "connector_id", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "connector_id": self.connector_id,
            "status": self.status,
            "auth_type": self.auth_type,
            "account_identifier": self.account_identifier,
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


