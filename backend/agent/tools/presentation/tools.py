"""NEXUS Tool subclasses for PowerPoint presentation automation."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.presentation.adapter import presentation_adapter
from backend.agent.tools.presentation.verifier import verify_presentation
from backend.core.file_dialog import open_native_save_dialog

logger = logging.getLogger("nexus.presentation_tools")


class PresentationCreateTool(NexusTool):
    name = "presentation_create"
    description = (
        "Create a professional PowerPoint presentation (.pptx) on a given topic with structured "
        "16:9 widescreen slides, executive theme, key takeaways, metrics, conclusion, and "
        "automatic web picture search and placement in appropriate slide positions."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        topic: str,
        theme: Optional[str] = "executive_navy",
        num_slides: int = 6,
        session_id: Optional[str] = None,
        custom_data: Optional[dict] = None,
        include_images: bool = True,
        **kwargs,
    ) -> ToolResult:
        try:
            clean_topic = topic.strip()
            sid, staging_path, data = await presentation_adapter.create_presentation(
                topic=clean_topic,
                theme=theme or "executive_navy",
                num_slides=num_slides or 6,
                session_id=session_id,
                custom_data=custom_data,
                include_images=include_images,
            )

            sanitized_name = re.sub(r"[^\w\s-]", "", data.topic).strip().replace(" ", "_")
            if not sanitized_name:
                sanitized_name = "presentation"
            default_filename = f"{sanitized_name}.pptx"

            image_count = sum(1 for s in data.slides if s.image_path)
            img_suffix = f" with {image_count} relevant web pictures placed" if image_count > 0 else ""

            summary = (
                f"Generated PowerPoint presentation '{data.title}' with {len(data.slides)} slides "
                f"using '{data.theme}' theme{img_suffix}. Staged at '{staging_path}'."
            )

            return ToolResult(
                success=True,
                output=summary,
                metadata={
                    "session_id": sid,
                    "topic": data.topic,
                    "title": data.title,
                    "slide_count": len(data.slides),
                    "image_count": image_count,
                    "staging_path": str(staging_path),
                    "default_filename": default_filename,
                },
            )
        except Exception as err:
            logger.error(f"presentation_create failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create PowerPoint presentation: {err}")


class PresentationSaveTool(NexusTool):
    name = "presentation_save"
    description = (
        "Save the PowerPoint presentation session to disk at the user's chosen location "
        "(Desktop, Documents, Downloads, or native File Explorer dialog)."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        path: Optional[str] = None,
        session_id: Optional[str] = None,
        default_filename: Optional[str] = None,
        topic: Optional[str] = None,
        reveal: bool = True,
        **kwargs,
    ) -> ToolResult:
        try:
            chosen_path = str(path).strip() if path else ""

            # If path is not provided, is a placeholder, or explicitly asks for user interaction
            if not chosen_path or chosen_path == "{{target_path}}" or chosen_path.lower() in ("ask", "choose", "select"):
                target_def_name = default_filename or "presentation.pptx"
                if not target_def_name.lower().endswith(".pptx"):
                    target_def_name += ".pptx"

                try:
                    from backend.api.nexus import request_user_input, _task_queues
                    active_ids = list(_task_queues.keys())
                    tid = active_ids[-1] if active_ids else "active_task"

                    prompt_text = f"PowerPoint presentation created! Where would you like to store the presentation ({target_def_name})?"
                    options_list = [
                        "Desktop",
                        "Documents",
                        "Downloads",
                        "Choose via File Explorer...",
                    ]

                    user_val = await request_user_input(
                        tid,
                        prompt=prompt_text,
                        options=options_list,
                        placeholder=f"Select location or enter path (e.g. Desktop/{target_def_name})...",
                    )

                    chosen_path = str(user_val).strip()

                    # Handle native Windows File Explorer request
                    if any(k in chosen_path.lower() for k in ("explorer", "browse", "file dialog", "select file")):
                        dialog_path = open_native_save_dialog(
                            default_filename=target_def_name,
                            title="Choose Where to Store PowerPoint Presentation",
                        )
                        if dialog_path:
                            chosen_path = dialog_path
                        else:
                            # Fallback if user dismissed dialog without selecting
                            chosen_path = f"Desktop/{target_def_name}"

                except Exception as user_err:
                    logger.warning(f"Could not request interactive user path for presentation: {user_err}")
                    chosen_path = f"Desktop/{target_def_name}"

            # Check if user selected one of the shorthand options
            lower_choice = chosen_path.lower()
            if lower_choice in ("desktop", "documents", "downloads"):
                target_def_name = default_filename or "presentation.pptx"
                if not target_def_name.lower().endswith(".pptx"):
                    target_def_name += ".pptx"
                chosen_path = f"{lower_choice.capitalize()}/{target_def_name}"

            # Save via adapter
            sid, saved_file = presentation_adapter.save_session(
                session_id=session_id,
                output_path=chosen_path,
                default_filename=default_filename,
            )

            out_msg = f"Successfully saved PowerPoint presentation to: {saved_file}"
            if reveal and presentation_adapter.reveal_in_explorer(saved_file):
                out_msg += "\nOpened in File Explorer."

            return ToolResult(
                success=True,
                output=out_msg,
                metadata={
                    "session_id": sid,
                    "path": str(saved_file),
                    "filename": saved_file.name,
                },
            )

        except Exception as err:
            logger.error(f"presentation_save failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to save presentation: {err}")


class PresentationReadTool(NexusTool):
    name = "presentation_read"
    description = "Inspect and retrieve structural stats (slide count, slide titles, topic) of a PPTX file or active session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            target = path or session_id or ""
            stats = presentation_adapter.read_session_stats(target)
            return ToolResult(
                success=True,
                output=json.dumps(stats.model_dump(), indent=2),
                metadata=stats.model_dump(),
            )
        except Exception as err:
            logger.error(f"presentation_read failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read presentation: {err}")


class PresentationVerifyTool(NexusTool):
    name = "presentation_verify"
    description = "Verify that a saved PowerPoint presentation (.pptx) exists on disk, is non-empty, and has valid slides."
    risk_level = RiskLevel.READ_ONLY

    async def execute(
        self,
        path: str,
        min_slides: int = 1,
        topic: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            passed, stats, err_msg = verify_presentation(
                file_path=path,
                min_slides=min_slides,
                required_topic=topic,
            )

            if not passed:
                return ToolResult(
                    success=False,
                    output=json.dumps({"verified": False, "error": err_msg}),
                    error=err_msg,
                )

            return ToolResult(
                success=True,
                output=f"Verified PowerPoint presentation at '{stats.get('resolved_path')}': {stats.get('slide_count')} slides intact.",
                metadata=stats,
            )
        except Exception as err:
            logger.error(f"presentation_verify failed: {err}")
            return ToolResult(success=False, output="", error=f"Verification failed: {err}")
