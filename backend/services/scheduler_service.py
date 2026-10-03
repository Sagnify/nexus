"""
Scheduler Background Engine for N.E.X.U.S.
Manages persistent scheduled reminders and automated task executions.
Reuses the existing N.E.X.U.S. agent pipeline, guarantees idempotency,
protects against overlapping runs via atomic claiming, performs pre-flight connector checks,
and extracts produced file artifacts into execution history.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import uuid
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.database.session import AsyncSessionLocal
from backend.database.repositories.scheduled_task_repo import ScheduledTaskRepository
from backend.database.models import ScheduledTask, ScheduledTaskRun
from backend.services.schedule_parser import calculate_next_run, get_safe_timezone
from backend.services.notification_service import send_user_notification

logger = logging.getLogger("nexus.scheduler")


class SchedulerService:
    def __init__(self, poll_interval_seconds: int = 15):
        self.poll_interval = poll_interval_seconds
        self.worker_id = f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._poll_loop(), name="nexus_scheduler_loop")
        logger.info("[Scheduler] Started background scheduler engine (%s, poll interval: %ds).", self.worker_id, self.poll_interval)

    async def stop(self) -> None:
        """Stop the background scheduler loop gracefully."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("[Scheduler] Stopped background scheduler engine.")

    async def _poll_loop(self) -> None:
        """Periodic poll loop checking for due scheduled tasks."""
        await asyncio.sleep(5)

        while not self._stop_event.is_set():
            try:
                await self._process_due_tasks()
            except Exception as exc:
                exc_type = type(exc).__name__
                err_str = str(exc) or exc_type
                lower_diag = (err_str + " " + exc_type).lower()
                if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionResetError, OSError)) or any(x in lower_diag for x in ("timeout", "getaddrinfo failed", "connecterror", "connection refused", "operationalerror", "cancellederror", "dbapierror", "cannot connect", "10054", "forcibly closed", "connection reset", "remote host")):
                    logger.debug("[Scheduler] Database connection reset or temporarily unreachable (%s). Will retry next poll interval.", err_str)
                else:
                    logger.error("[Scheduler] Error during task polling tick: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _process_due_tasks(self) -> None:
        """Query and execute all due tasks in PostgreSQL with offline/timeout protection."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        try:
            from backend.database.session import safe_db_context
            async with safe_db_context() as session:
                if session is None:
                    return
                repo = ScheduledTaskRepository(session)
                due_tasks = await repo.get_due_tasks(now_utc)
                if not due_tasks:
                    return

                logger.info("[Scheduler] Worker %s found %d due scheduled task(s).", self.worker_id, len(due_tasks))

                for task in due_tasks:
                    asyncio.create_task(self._execute_scheduled_task(task.id))
        except (TimeoutError, asyncio.TimeoutError) as te:
            logger.debug("[Scheduler] Database warming up or timeout during scheduled task poll: %s", te)
        except Exception as exc:
            err_str = str(exc).lower()
            if "timeout" in err_str or "connection" in err_str or "closed" in err_str:
                logger.debug("[Scheduler] Database warming up during poll: %s", exc)
            else:
                logger.warning("[Scheduler] Error querying due tasks: %s", exc)

    async def _execute_scheduled_task(self, task_id: uuid.UUID) -> None:
        """Execute a single due task with overlap protection and idempotency checks."""
        from backend.database.session import safe_db_context
        async with safe_db_context() as session:
            if session is None:
                return
            repo = ScheduledTaskRepository(session)
            task = await repo.get_by_id(task_id)
            if not task or not task.enabled:
                return

            scheduled_for = task.next_run_at
            if not scheduled_for:
                return

            # Overlap protection: skip if previous run is still active
            is_running = await repo.is_task_currently_running(task.id)
            if is_running:
                logger.warning("[Scheduler] Task %s (%s) is already running. Skipping overlap.", task.id, task.name)
                return

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=datetime.timezone.utc)

            # Check missed task policy (threshold 15 mins)
            delay_seconds = (now_utc - scheduled_for).total_seconds()
            is_missed = delay_seconds > 900

            # Create run record with unique constraint guard
            run = await repo.create_run(
                scheduled_task_id=task.id,
                user_id=task.user_id,
                scheduled_for=scheduled_for,
                status="pending",
                metadata_json={"missed_delay_seconds": max(0, delay_seconds)},
            )
            await session.commit()

            if not run or run.status in ("running", "completed", "blocked"):
                return

            # Advance next_run_at immediately to prevent duplicate pick-up in next tick
            next_run = calculate_next_run(task.schedule_type, task.schedule_definition, task.timezone, now_utc)

            if is_missed and task.missed_policy == "skip" and task.task_type == "automation":
                logger.info("[Scheduler] Task %s was missed by %ds; skipping per policy.", task.name, delay_seconds)
                await repo.update_run(
                    run.id,
                    status="skipped",
                    completed_at=now_utc,
                    result=f"Skipped per missed policy (was scheduled for {scheduled_for.isoformat()})",
                )
                await repo.update_after_run(task.id, last_run_at=now_utc, next_run_at=next_run, success=True, status_override="skipped")
                await session.commit()
                return

            # Route execution based on task_type
            if task.task_type == "reminder":
                await self._execute_reminder(repo, task, run, scheduled_for, next_run, is_missed, session=session)
            else:
                await self._execute_automation(repo, task, run, scheduled_for, next_run, session=session)

            await session.commit()

    async def _execute_reminder(
        self,
        repo: ScheduledTaskRepository,
        task: ScheduledTask,
        run: ScheduledTaskRun,
        scheduled_for: datetime.datetime,
        next_run: Optional[datetime.datetime],
        is_missed: bool,
        session: Any = None,
    ) -> None:
        """Execute a reminder task (notification only)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        execution_id = f"rem_{task.id.hex[:8]}_{int(now.timestamp())}"

        # Atomic claim
        claimed_run = await repo.claim_pending_run(run.id, self.worker_id, execution_id, now)
        if not claimed_run:
            logger.info("[Scheduler] Reminder %s was claimed by another worker; skipping.", run.id)
            return

        title = f"Reminder: {task.name}"
        if is_missed:
            title = f"Reminder (Missed): {task.name}"

        message = task.prompt
        await send_user_notification(title, message, notification_type="reminder", speak=True)

        completed_at = datetime.datetime.now(datetime.timezone.utc)
        await repo.update_run(
            run.id,
            status="completed",
            completed_at=completed_at,
            result=f"Delivered reminder: {message}",
        )
        await repo.update_after_run(task.id, last_run_at=completed_at, next_run_at=next_run, success=True, status_override="completed")
        if session:
            await session.commit()
        logger.info("[Scheduler] Completed reminder '%s' (next run: %s).", task.name, next_run)

    async def _execute_automation(
        self,
        repo: ScheduledTaskRepository,
        task: ScheduledTask,
        run: ScheduledTaskRun,
        scheduled_for: datetime.datetime,
        next_run: Optional[datetime.datetime],
        session: Any = None,
    ) -> None:
        """
        Execute an automated task by reusing the existing N.E.X.U.S. pipeline.
        Invokes run_agent_workflow with NexusState, performs pre-flight connector checks,
        and collects generated artifacts into execution history.
        """
        from backend.api.nexus import (
            run_agent_workflow,
            _task_states,
            _task_queues,
            _task_pause_events,
            _token_callbacks,
            _task_background_jobs,
        )
        from backend.core.targets import target_manager
        from backend.agent.state import NexusState
        from backend.connectors.credentials_store import credentials_store

        now = datetime.datetime.now(datetime.timezone.utc)
        execution_id = f"sched_{task.id.hex[:8]}_{int(now.timestamp())}"

        # 1. Atomic DB Claim
        claimed_run = await repo.claim_pending_run(run.id, self.worker_id, execution_id, now)
        if not claimed_run:
            logger.info("[Scheduler] Run %s already claimed by another worker. Skipping.", run.id)
            return

        exec_cfg = task.execution_config or {}

        # 2. Pre-flight Connector Check
        required_connectors = exec_cfg.get("required_connectors", [])
        for conn_id in required_connectors:
            token = credentials_store.get_token(str(task.user_id), conn_id)
            if not token or not token.get("access_token"):
                err_msg = f"Connector '{conn_id}' is required but disconnected. Re-authorize under Settings -> Connectors."
                logger.warning("[Scheduler] Task '%s' blocked: %s", task.name, err_msg)
                completed_at = datetime.datetime.now(datetime.timezone.utc)
                await repo.update_run(
                    run.id,
                    status="blocked",
                    completed_at=completed_at,
                    error=err_msg,
                )
                await repo.update_after_run(task.id, last_run_at=completed_at, next_run_at=next_run, success=False, status_override="blocked")
                if session:
                    await session.commit()
                notification_action = None
                if (task.normalized_intent or {}).get("action") == "gmail_brief_messages":
                    notification_action = {
                        "type": "email_brief",
                        "task_id": str(task.id),
                        "run_id": str(run.id),
                    }
                await send_user_notification(
                    f"Scheduled Automation Blocked: {task.name}",
                    f"Action Required: '{conn_id}' connector authorization missing.",
                    notification_type="email_brief" if notification_action else "automation",
                    action=notification_action,
                )
                return

        # 3. Dynamic Context & Prompt Preparation
        prompt_template = exec_cfg.get("clean_prompt_template") or task.prompt
        tz = get_safe_timezone(task.timezone)
        local_now = datetime.datetime.now(tz)
        date_str = local_now.strftime("%Y-%m-%d")
        datetime_str = local_now.strftime("%Y-%m-%d %H:%M:%S")

        runtime_prompt = prompt_template.replace("{date}", date_str).replace("{datetime}", datetime_str)
        intent_cat = (task.normalized_intent or {}).get("category") or "general"

        try:
            cur_target = target_manager.get_active_target().model_dump()
            cur_context = target_manager.refresh_current_context().model_dump()
        except Exception:
            cur_target = {"id": "antigravity", "application": "Antigravity", "target_type": "antigravity"}
            cur_context = {}

        queue = asyncio.Queue()
        _task_queues[execution_id] = queue
        p_event = asyncio.Event()
        p_event.set()
        _task_pause_events[execution_id] = p_event

        initial_state: NexusState = {
            "task_id": execution_id,
            "user_id": str(task.user_id),
            "user_input": runtime_prompt,
            "messages": [{"role": "user", "content": runtime_prompt}],
            "intent": intent_cat,
            "goal": runtime_prompt,
            "plan": [],
            "current_step": 0,
            "selected_model": "qwen/qwen3.8-27b",
            "model_history": [],
            "memory_context": [],
            "tool_calls": [],
            "tool_results": [],
            "observations": [],
            "screen_context": None,
            "permission_required": False,
            "permission_status": "none",
            "permission_items": [],
            "execution_status": "thinking",
            "retry_count": 0,
            "max_retries": 3,
            "notification_events": [],
            "final_response": None,
            "spoken_response": None,
            "error": None,
            "execution_history": [],
            "goal_achieved": False,
            "max_iterations": 20,
            "verification_retries": 0,
            "verification_details": None,
            "active_target": cur_target,
            "active_context": cur_context,
        }
        _task_states[execution_id] = initial_state

        logger.info("[Scheduler] Triggering N.E.X.U.S. workflow for scheduled automation '%s' (id: %s)...", task.name, execution_id)

        # 4. Execute workflow through the standard agent graph
        workflow_task = asyncio.create_task(run_agent_workflow(execution_id, initial_state))
        _task_background_jobs[execution_id] = workflow_task

        try:
            await workflow_task
        except Exception as exc:
            logger.error("[Scheduler] Error executing workflow %s: %s", execution_id, exc)

        completed_at = datetime.datetime.now(datetime.timezone.utc)
        final_state = _task_states.get(execution_id, {})
        status = final_state.get("execution_status", "completed")
        success = status == "completed"
        final_resp = final_state.get("final_response") or "Scheduled task completed."
        err_msg = final_state.get("error")

        # 5. Extract Artifacts
        artifacts = self._collect_artifacts(final_state, exec_cfg, local_now)

        await repo.update_run(
            run.id,
            status="completed" if success else "failed",
            completed_at=completed_at,
            result=final_resp if success else None,
            error=err_msg if not success else None,
            artifacts=artifacts,
        )
        await repo.update_after_run(task.id, last_run_at=completed_at, next_run_at=next_run, success=success, status_override="completed" if success else "failed")
        if session:
            await session.commit()

        # Notify user of completion or failure
        title = f"Scheduled Automation: {task.name}"
        notification_action = None
        is_email_brief = (task.normalized_intent or {}).get("action") == "gmail_brief_messages"
        if is_email_brief:
            notification_action = {
                "type": "email_brief",
                "task_id": str(task.id),
                "run_id": str(run.id),
            }
        if success:
            body = f"Success. Generated {len(artifacts)} artifact(s)." if artifacts else final_resp[:120]
            if is_email_brief:
                title = "Your email brief is ready"
                body = final_resp[:220]
        else:
            if is_email_brief:
                title = "Email brief could not be created"
            body = f"Execution failed: {err_msg or 'unknown error'}"
        await send_user_notification(
            title,
            body,
            notification_type="email_brief" if notification_action else "automation",
            action=notification_action,
        )

    def _collect_artifacts(
        self,
        final_state: dict[str, Any],
        exec_cfg: dict[str, Any],
        execution_time: datetime.datetime,
    ) -> list[dict[str, Any]]:
        """Extract created document, spreadsheet, and presentation files from state and filesystem."""
        artifacts: list[dict[str, Any]] = []
        seen_paths = set()

        mime_map = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pdf": "application/pdf",
            ".csv": "text/csv",
            ".json": "application/json",
            ".md": "text/markdown",
        }

        # 1. Scan tool_results for file paths
        tool_results = final_state.get("tool_results", [])
        for res in tool_results:
            text = str(res)
            matches = re.findall(r"([a-zA-Z]:[\\/][^\s\"'<>]+?\.(?:docx|xlsx|pptx|pdf|csv|json|md))", text, re.IGNORECASE)
            for p in matches:
                norm_p = os.path.normpath(p)
                if norm_p not in seen_paths and os.path.exists(norm_p):
                    seen_paths.add(norm_p)
                    try:
                        stat = os.stat(norm_p)
                        ext = os.path.splitext(norm_p)[1].lower()
                        artifacts.append({
                            "name": os.path.basename(norm_p),
                            "path": norm_p,
                            "size_bytes": stat.st_size,
                            "mime_type": mime_map.get(ext, "application/octet-stream"),
                            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
                        })
                    except Exception as e:
                        logger.debug("Error reading artifact %s: %s", norm_p, e)

        # 2. Check filename template if configured
        template = exec_cfg.get("filename_template")
        if template:
            date_str = execution_time.strftime("%Y-%m-%d")
            expected_name = template.replace("{date}", date_str)
            search_roots = [os.getcwd(), os.path.join(os.getcwd(), "artifacts")]
            for root in search_roots:
                candidate = os.path.normpath(os.path.join(root, expected_name))
                if candidate not in seen_paths and os.path.exists(candidate):
                    seen_paths.add(candidate)
                    try:
                        stat = os.stat(candidate)
                        ext = os.path.splitext(candidate)[1].lower()
                        artifacts.append({
                            "name": expected_name,
                            "path": candidate,
                            "size_bytes": stat.st_size,
                            "mime_type": mime_map.get(ext, "application/octet-stream"),
                            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass

        return artifacts

    async def trigger_run_now(self, task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[ScheduledTaskRun]:
        """Manually trigger an immediate run of a scheduled task."""
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.get_by_id(task_id, user_id=user_id)
            if not task:
                return None

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            run = await repo.create_run(
                scheduled_task_id=task.id,
                user_id=task.user_id,
                scheduled_for=now_utc,
                status="pending",
                metadata_json={"trigger": "manual_run_now"},
            )
            await session.commit()

            asyncio.create_task(self._execute_ad_hoc_run(task.id, run.id))
            return run

    async def _execute_ad_hoc_run(self, task_id: uuid.UUID, run_id: uuid.UUID) -> None:
        """Handle immediate manual execution."""
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.get_by_id(task_id)
            run = await repo.get_run_by_id(run_id)
            if not task or not run:
                return

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            next_run = calculate_next_run(task.schedule_type, task.schedule_definition, task.timezone, now_utc)

            if task.task_type == "reminder":
                await self._execute_reminder(repo, task, run, now_utc, next_run, is_missed=False, session=session)
            else:
                await self._execute_automation(repo, task, run, now_utc, next_run, session=session)

            await session.commit()


scheduler_service = SchedulerService(poll_interval_seconds=15)
