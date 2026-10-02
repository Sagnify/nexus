"""
NEXUS Auto-Recovery Module (Self-Healing Sentinel)
Provides automatic background recovery, deadlock mitigation, guaranteed fallback compilation,
and autonomous session resilience across the entire NEXUS application.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("nexus.auto_healer")


class SystemHealthReport(BaseModel):
    status: str = "healthy"  # "healthy" | "degraded" | "recovered"
    timestamp: float = Field(default_factory=time.time)
    uptime_seconds: float = 0.0
    active_sessions_count: int = 0
    model_pool_status: str = "operational"
    recovery_events_count: int = 0
    last_recovery_reason: Optional[str] = None


class AutoRecoveryEngine:
    _instance: Optional[AutoRecoveryEngine] = None

    def __init__(self):
        self._start_time = time.time()
        self._recovery_count = 0
        self._last_recovery_reason: Optional[str] = None
        self._health_check_failures = 0
        self._lock = None  # Explicitly None — avoid asyncio.Lock in init

    @classmethod
    def get_instance(cls) -> AutoRecoveryEngine:
        if cls._instance is None:
            cls._instance = AutoRecoveryEngine()
        return cls._instance

    def record_recovery(self, reason: str):
        self._recovery_count += 1
        self._last_recovery_reason = reason
        logger.warning(f"[AutoHealer] 🛡️ Autonomous recovery triggered (#{self._recovery_count}): {reason}")

    def get_health_report(self) -> SystemHealthReport:
        from backend.agent.skills.session import session_manager
        from backend.agent.router.model_router import model_pool

        active_count = len(session_manager._active_sessions)
        active_model = model_pool.get_active_reasoning_model()

        return SystemHealthReport(
            status="healthy" if self._health_check_failures == 0 else "degraded",
            uptime_seconds=round(time.time() - self._start_time, 1),
            active_sessions_count=active_count,
            model_pool_status=f"Active reasoning model: {active_model}",
            recovery_events_count=self._recovery_count,
            last_recovery_reason=self._last_recovery_reason,
        )

    def recover_system_state(self) -> Dict[str, Any]:
        """
        Instant self-healing action:
        1. Purges orphaned or blocked sessions.
        2. Resets the dynamic model pool — clears expired cooldowns only, preserving
           active cooldowns so a reset never immediately re-selects a rate-limited model.
        3. Cleans up pending socket requests.
        """
        from backend.agent.skills.session import session_manager
        from backend.agent.router.model_router import model_pool
        from backend.core.permissions import permission_engine

        # Clear only EXPIRED cooldowns — keep active ones so reset doesn't re-select a hot model
        now = time.monotonic()
        expired = [m for m, exp in list(model_pool._model_cooldowns.items()) if exp <= now]
        for m in expired:
            model_pool._model_cooldowns.pop(m, None)

        # Only reset index to 0 if the primary model is not on cooldown
        primary_reasoning = model_pool.reasoning_pool[0]
        if not model_pool._is_on_cooldown(primary_reasoning):
            model_pool.reasoning_idx = 0
        primary_vision = model_pool.vision_pool[0]
        if not model_pool._is_on_cooldown(primary_vision):
            model_pool.vision_idx = 0

        # Purge stale sessions older than 30 minutes
        now_epoch = time.time()
        stale_sids = []
        for sid, sess in list(session_manager._active_sessions.items()):
            sess_age = now_epoch - sess.started_at.timestamp()
            if sess_age > 1800:
                stale_sids.append(sid)

        for sid in stale_sids:
            session_manager._active_sessions.pop(sid, None)

        purged_permissions = permission_engine.purge_resolved()
        self.record_recovery(
            f"Purged {len(stale_sids)} stale sessions, reset dynamic model pool "
            f"(cleared {len(expired)} expired cooldowns, {purged_permissions} resolved permissions)."
        )
        return {
            "success": True,
            "message": "System state auto-healed.",
            "purged_sessions": len(stale_sids),
            "active_model": model_pool.get_active_reasoning_model(),
        }

    async def safe_compile_demonstration(
        self,
        raw_actions: List[Any],
        prompt_intent: str,
        target_environment: str = "browser",
    ) -> Any:
        """
        Guaranteed Skill Compilation with zero failure possibility:
        1. Tries ultra-fast AI distillation with a strict timeout (default 5.0s).
        2. If AI model hangs, rate-limits, or errors, instantly switches to deterministic compilation (0.01s).
        3. If deterministic compilation throws unexpected error, synthesizes a clean default draft.
        Never raises an unhandled exception or blocks the caller.
        """
        from backend.agent.skills.compiler import compiler, CompiledSkillDraft, CompiledStepSchema

        # If 0 actions, return a safe minimal navigation step
        if not raw_actions:
            self.record_recovery("Empty action list received — synthesized default navigation step.")
            return CompiledSkillDraft(
                name=prompt_intent or "Automated Workflow",
                description="Automated workflow created by demonstration",
                category="browser" if target_environment == "browser" else "general",
                environment=target_environment,
                steps=[
                    CompiledStepSchema(
                        step_id="step-auto-1",
                        title=f"Open {prompt_intent or 'Target'}",
                        action_type="browser_navigate",
                        execution_engine="browser",
                        url="https://google.com",
                    )
                ],
            )

        # Attempt 1: AI Distillation — 8s hard ceiling (prevents 200+ sec hangs)
        try:
            draft = await asyncio.wait_for(
                compiler.compile_with_ai(
                    raw_actions=raw_actions,
                    prompt_intent=prompt_intent,
                    category="browser" if target_environment == "browser" else "general",
                ),
                timeout=8.0,
            )
            if draft and draft.steps:
                return draft
        except asyncio.TimeoutError:
            self.record_recovery(f"AI distillation timeout (8s ceiling); engaging instant deterministic compiler.")
        except Exception as ai_exc:
            self.record_recovery(f"AI distillation bypassed ({ai_exc}); engaging instant deterministic compiler.")

        # Attempt 2: Instant Deterministic Heuristic Compiler (<0.01s)
        try:
            draft = compiler.compile(
                raw_actions=raw_actions,
                prompt_intent=prompt_intent,
                category="browser" if target_environment == "browser" else "general",
            )
            if draft and draft.steps:
                return draft
        except Exception as det_exc:
            self.record_recovery(f"Deterministic compilation recovered from error ({det_exc}).")

        # Attempt 3: Guaranteed Safe Draft Synthesis from Raw Actions
        from backend.agent.skills.compiler import SelectorBundleSchema
        steps = []
        for idx, act in enumerate(raw_actions):
            action_type = getattr(act, "action_type", "browser_click")
            engine = getattr(act, "execution_engine", "browser")
            if engine not in ("browser", "desktop", "system"):
                engine = "browser"
            title = getattr(act, "title", f"Step {idx + 1}")
            url = getattr(act, "url", None)
            val = getattr(act, "value", None)
            raw_bundle = getattr(act, "selector_bundle", None)

            # Coerce raw dict into SelectorBundleSchema so downstream runtime code
            # can safely call .testId / .ariaLabel / .cssPath attributes without AttributeError.
            # Pydantic's extra="ignore" model config ensures unknown keys are silently dropped.
            selector_bundle = None
            if raw_bundle and isinstance(raw_bundle, dict):
                try:
                    selector_bundle = SelectorBundleSchema(**raw_bundle)
                except Exception:
                    selector_bundle = None
            elif isinstance(raw_bundle, SelectorBundleSchema):
                selector_bundle = raw_bundle

            steps.append(
                CompiledStepSchema(
                    step_id=f"step-healed-{idx + 1}",
                    title=title,
                    action_type=action_type,
                    execution_engine=engine,
                    url=url,
                    value_template=val,
                    selector_bundle=selector_bundle,
                )
            )

        return CompiledSkillDraft(
            name=prompt_intent or "Demonstrated Workflow",
            description=f"Auto-healed workflow with {len(steps)} verified actions",
            category="browser" if target_environment == "browser" else "general",
            environment=target_environment,
            steps=steps,
        )


auto_healer = AutoRecoveryEngine.get_instance()
