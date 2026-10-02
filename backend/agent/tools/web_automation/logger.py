"""NEXUS Persistent Automation Logger — records full step trajectories, DOM diffs,
validation tiers, low-confidence warnings, and model failovers."""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
from typing import Any, Optional

LOG_DIR = Path(__file__).resolve().parents[4] / "backend" / "logs"
LOG_TXT = LOG_DIR / "automation.log"
LOG_JSONL = LOG_DIR / "automation.jsonl"


class AutomationLogger:
    def __init__(self):
        self._ensure_dir()

    def _ensure_dir(self):
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _write_text(self, line: str):
        try:
            self._ensure_dir()
            with open(LOG_TXT, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _write_jsonl(self, data: dict):
        try:
            self._ensure_dir()
            data["timestamp"] = datetime.datetime.now().isoformat()
            with open(LOG_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, default=str) + "\n")
        except Exception:
            pass

    def log_step(
        self,
        step_idx: int,
        total_steps: int,
        action: str,
        args: dict,
        reasoning: str,
        result: str,
        success: bool,
        url: str = "",
    ):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_sym = "✓" if success else "✗"
        line = (
            f"[{now_str}] STEP {step_idx + 1}/{total_steps} | {status_sym} {action} | "
            f"URL: {url} | Reason: {reasoning} | Args: {json.dumps(args, default=str)[:140]} | Result: {result[:120]}"
        )
        self._write_text(line)
        self._write_jsonl({
            "event": "step",
            "step_index": step_idx,
            "total_steps": total_steps,
            "action": action,
            "args": args,
            "reasoning": reasoning,
            "result": result[:300],
            "success": success,
            "url": url,
        })

    def log_validation(
        self,
        action: str,
        passed: bool,
        confidence: float,
        tier: str,
        reason: str,
        suggestion: str = "",
    ):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "PASSED" if passed else "FAILED"
        line = (
            f"[{now_str}] VALIDATION | {status} (conf={confidence:.0%}, tier={tier}) | "
            f"Action: {action} | Reason: {reason} | Suggestion: {suggestion}"
        )
        self._write_text(line)
        self._write_jsonl({
            "event": "validation",
            "action": action,
            "passed": passed,
            "confidence": confidence,
            "tier": tier,
            "reason": reason,
            "suggestion": suggestion,
        })

        # Specially highlight low-confidence steps (< 0.65)
        if confidence < 0.65 or not passed:
            self.log_low_confidence(action, confidence, reason, suggestion)

    def log_low_confidence(
        self,
        action: str,
        confidence: float,
        reason: str,
        suggestion: str = "",
    ):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        warning = (
            f"\n{'!'*68}\n"
            f"[NEXUS AUTOMATION WARNING: LOW CONFIDENCE OBSERVATION]\n"
            f"Time: {now_str}\n"
            f"Action: {action}\n"
            f"Confidence: {confidence:.0%}\n"
            f"Reason: {reason}\n"
            f"Suggestion: {suggestion}\n"
            f"{'!'*68}\n"
        )
        print(warning, flush=True)
        self._write_text(f"[{now_str}] !!! LOW CONFIDENCE WARNING: {action} conf={confidence:.0%} - {reason}")
        self._write_jsonl({
            "event": "low_confidence_warning",
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "suggestion": suggestion,
        })

    def log_dom_diff(
        self,
        initial_url: str,
        final_url: str,
        added_elements: list[str],
        modified_values: list[dict],
        summary: str,
    ):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"[{now_str}] DOM DIFF | Initial URL: {initial_url} -> Final URL: {final_url} | "
            f"Added: {len(added_elements)} elements | Modified: {len(modified_values)} fields | Summary: {summary}"
        )
        self._write_text(line)
        self._write_jsonl({
            "event": "dom_diff",
            "initial_url": initial_url,
            "final_url": final_url,
            "added_elements": added_elements[:20],
            "modified_values": modified_values[:20],
            "summary": summary,
        })

    def log_model_switch(self, pool_type: str, old_model: str, new_model: str, reason: str):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"[{now_str}] MODEL SWITCH ({pool_type}) | '{old_model}' -> '{new_model}' | Reason: {reason}"
        )
        self._write_text(line)
        self._write_jsonl({
            "event": "model_switch",
            "pool_type": pool_type,
            "old_model": old_model,
            "new_model": new_model,
            "reason": reason,
        })

    def log_goal_verification(
        self,
        goal: str,
        passed: bool,
        confidence: float,
        reason: str,
        missing: list[Any] = None,
        tier: str = "dual",
    ):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "CONFIRMED SUCCESS" if passed else "INCOMPLETE / REJECTED"
        line = (
            f"[{now_str}] GOAL AUDIT | {status} (conf={confidence:.0%}, tier={tier}) | "
            f"Goal: {goal} | Reason: {reason} | Missing: {missing or []}"
        )
        self._write_text(line)
        self._write_jsonl({
            "event": "goal_audit",
            "goal": goal,
            "passed": passed,
            "confidence": confidence,
            "reason": reason,
            "missing": missing or [],
            "tier": tier,
        })


auto_logger = AutomationLogger()
