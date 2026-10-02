"""
Schedule Parser Service for N.E.X.U.S.
Parses natural language scheduling requests, detects ambiguities, computes timezone-aware
next run times, classifies tasks into 'reminder' or 'automation', and extracts
structured normalized_intent and execution_config (static vs. dynamic parameters).
"""
from __future__ import annotations

import re
import json
import logging
from datetime import datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from pydantic import BaseModel, Field

logger = logging.getLogger("nexus.schedule_parser")

DEFAULT_TIMEZONE = "Asia/Kolkata"

WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

REVERSE_WEEKDAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday",
    3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"
}

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class ScheduleParseResult(BaseModel):
    is_schedule: bool = False
    task_type: str = "reminder"  # "reminder" | "automation"
    name: str = ""
    prompt: str = ""
    schedule_type: str = "one_time"  # "one_time" | "recurring"
    schedule_definition: dict[str, Any] = Field(default_factory=dict)
    timezone: str = DEFAULT_TIMEZONE
    next_run_at: Optional[datetime] = None
    is_ambiguous: bool = False
    clarification_question: Optional[str] = None
    confidence: float = 0.0
    normalized_intent: dict[str, Any] = Field(default_factory=dict)
    execution_config: dict[str, Any] = Field(default_factory=dict)


def get_safe_timezone(tz_name: Optional[str]) -> Any:
    """Safely get ZoneInfo, falling back to DEFAULT_TIMEZONE or UTC."""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        try:
            return ZoneInfo("UTC")
        except Exception:
            return timezone.utc


def calculate_next_run(
    schedule_type: str,
    schedule_definition: dict[str, Any],
    timezone_str: str = DEFAULT_TIMEZONE,
    from_time: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Calculate the next occurrence datetime in the target timezone.
    Always returns a timezone-aware datetime.
    """
    tz = get_safe_timezone(timezone_str)
    now = from_time if from_time is not None else datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    frequency = schedule_definition.get("frequency", "once")

    if schedule_type == "one_time" or frequency == "once":
        target_str = schedule_definition.get("target_time")
        if not target_str:
            return None
        try:
            parsed_dt = dateutil_parser.isoparse(target_str)
        except Exception:
            try:
                parsed_dt = dateutil_parser.parse(target_str)
            except Exception:
                return None
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=tz)
        else:
            parsed_dt = parsed_dt.astimezone(tz)
        return parsed_dt

    time_str = schedule_definition.get("time", "09:00")
    try:
        target_hour, target_minute = map(int, time_str.split(":"))
    except Exception:
        target_hour, target_minute = 9, 0

    if frequency == "interval":
        interval_mins = int(schedule_definition.get("interval_minutes", 60))
        return now + timedelta(minutes=max(1, interval_mins))

    if frequency == "daily":
        candidate = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if frequency == "weekdays":
        candidate = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        # 0=Monday ... 4=Friday, 5=Saturday, 6=Sunday
        if candidate <= now or candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            while candidate.weekday() >= 5:
                candidate += timedelta(days=1)
        return candidate

    if frequency == "weekly":
        target_days = schedule_definition.get("days", ["monday"])
        target_day_indices = set()
        for d in target_days:
            clean = str(d).strip().lower()
            if clean in WEEKDAY_MAP:
                target_day_indices.add(WEEKDAY_MAP[clean])
        if not target_day_indices:
            target_day_indices.add(0)  # default Monday

        candidate = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        # Look ahead up to 7 days
        for day_offset in range(8):
            test_dt = candidate + timedelta(days=day_offset)
            if test_dt.weekday() in target_day_indices:
                if test_dt > now:
                    return test_dt

        # Fallback to next week's first matching day
        return candidate + timedelta(days=7)

    if frequency == "monthly":
        day_of_month = int(schedule_definition.get("day_of_month", 1))
        candidate = now.replace(day=min(day_of_month, 28), hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + relativedelta(months=1)
        return candidate

    return None


class ScheduleParser:
    def __init__(self, default_tz: str = DEFAULT_TIMEZONE):
        self.default_tz = default_tz

    def _extract_automation_metadata(
        self,
        clean_prompt: str,
        raw_text: str,
        is_explicit_reminder: bool = False,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """
        Analyze prompt to categorize intent and extract static parameters vs dynamic templates.
        Returns: (task_type, normalized_intent, execution_config)
        """
        p_lower = clean_prompt.lower()
        r_lower = raw_text.lower()

        # 1. Email intent (e.g. "Send John a happy birthday email", "On October 15, send this email")
        if re.search(r"\b(?:send|draft|forward)\b", p_lower) and re.search(r"\b(?:email|mail)\b", p_lower) or re.search(r"\b(?:email|mail)\b", p_lower):
            # Recipient detection
            recipient = ""
            recip_match = re.search(r"(?:to|send)\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", clean_prompt, re.IGNORECASE)
            if recip_match:
                recipient = recip_match.group(1).strip()
            else:
                name_match = re.search(r"(?:send\s+(?!an?\b|the\b|this\b)([a-zA-Z]+)|to\s+(?!an?\b|the\b|this\b)([a-zA-Z]+))", clean_prompt, re.IGNORECASE)
                if name_match:
                    recipient = (name_match.group(1) or name_match.group(2) or "").strip()

            # Subject detection
            subject = ""
            if "birthday" in p_lower:
                subject = "Happy Birthday"
            elif "report" in p_lower:
                subject = "Scheduled Report"
            else:
                subj_match = re.search(r"(?:subject|about)\s+['\"]?([^'\",.]+)['\"]?", clean_prompt, re.IGNORECASE)
                if subj_match:
                    subject = subj_match.group(1).strip()

            normalized_intent = {
                "category": "email",
                "action": "gmail_send_email",
                "target": recipient or "recipient",
                "subject": subject,
            }
            execution_config = {
                "action_type": "email",
                "required_connectors": ["gmail"],
                "recipient": recipient,
                "subject": subject,
                "clean_prompt_template": clean_prompt,
            }
            return "automation", normalized_intent, execution_config

        # 2. Document Creation & Deep Research (e.g. "research the latest developments in AI agents and create a Word document")
        if re.search(r"\b(?:word document|\.docx|docx|word doc)\b", p_lower):
            topic = "latest developments in AI agents"
            topic_match = re.search(r"research\s+(?:the\s+)?(latest developments in [^,.\n]+|latest news about [^,.\n]+|[^,.\n]+)", clean_prompt, re.IGNORECASE)
            if topic_match:
                topic = topic_match.group(1).replace("and create a Word document", "").replace("and create a word document", "").strip()

            clean_topic_slug = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")
            if len(clean_topic_slug) > 30:
                clean_topic_slug = clean_topic_slug[:30]
            filename_template = f"{clean_topic_slug or 'Research'}_{{date}}.docx"

            normalized_intent = {
                "category": "research_doc",
                "action": "create_word_document",
                "topic": topic,
                "output_format": "docx",
            }
            execution_config = {
                "action_type": "research_doc",
                "output_format": "docx",
                "topic": topic,
                "filename_template": filename_template,
                "clean_prompt_template": f"Perform fresh web research on {topic} as of {{date}}, synthesize key findings, and create a Word document saved to '{filename_template}'.",
            }
            return "automation", normalized_intent, execution_config

        # 3. Spreadsheet / Excel Report (e.g. "create my weekly Excel report")
        if re.search(r"\b(?:excel|spreadsheet|\.xlsx|xlsx)\b", p_lower):
            filename_template = "Weekly_Report_{date}.xlsx"
            normalized_intent = {
                "category": "spreadsheet",
                "action": "create_excel_report",
                "output_format": "xlsx",
            }
            execution_config = {
                "action_type": "spreadsheet",
                "output_format": "xlsx",
                "filename_template": filename_template,
                "clean_prompt_template": f"Generate the weekly Excel report for the week of {{date}} saved to '{filename_template}'.",
            }
            return "automation", normalized_intent, execution_config

        # 4. PowerPoint Presentation (e.g. "create a PowerPoint presentation from this research")
        if re.search(r"\b(?:powerpoint|presentation|\.pptx|pptx|slide deck)\b", p_lower):
            filename_template = "Presentation_{date}.pptx"
            normalized_intent = {
                "category": "presentation",
                "action": "create_powerpoint_presentation",
                "output_format": "pptx",
            }
            execution_config = {
                "action_type": "presentation",
                "output_format": "pptx",
                "filename_template": filename_template,
                "clean_prompt_template": f"Create a PowerPoint presentation summarizing the research and save to '{filename_template}'.",
            }
            return "automation", normalized_intent, execution_config

        # 5. Project / Error Checking (e.g. "check my project and tell me if there are any errors")
        if re.search(r"\b(?:check my project|errors? in (?:my )?project|test my project)\b", p_lower):
            normalized_intent = {
                "category": "code_check",
                "action": "check_project_errors",
            }
            execution_config = {
                "action_type": "code_check",
                "clean_prompt_template": "Check my project for any errors, linting issues, or failed tests and summarize findings.",
            }
            return "automation", normalized_intent, execution_config

        # 6. General Research & Summary / Report
        if (re.search(r"\b(?:research|search)\b", p_lower) and re.search(r"\b(?:summary|summarize|report|analysis|brief|findings|news|developments|agents)\b", p_lower)) or re.search(r"\bresearch\s+report\b", p_lower):
            topic_match = re.search(r"research\s+(?:report\s+on\s+|the\s+)?(latest news about [^,.\n]+|latest developments in [^,.\n]+|[^,.\n]+)", clean_prompt, re.IGNORECASE)
            raw_topic = topic_match.group(1) if topic_match else "latest news"
            topic = re.sub(r"(?:and\s+create\s+a\s+(?:summary|report)|and\s+summarize)", "", raw_topic, flags=re.IGNORECASE).strip()
            topic = re.sub(r"^(?:report\s+on\s+|on\s+)", "", topic, flags=re.IGNORECASE).strip()
            normalized_intent = {
                "category": "research",
                "action": "web_research_summary",
                "topic": topic,
            }
            execution_config = {
                "action_type": "research",
                "topic": topic,
                "clean_prompt_template": f"Perform fresh research on {topic} as of {{date}} and create a comprehensive summary.",
            }
            return "automation", normalized_intent, execution_config

        # 7. Explicit Reminder
        if is_explicit_reminder:
            normalized_intent = {
                "category": "reminder",
                "action": "send_notification",
            }
            execution_config = {
                "action_type": "reminder",
                "clean_prompt_template": clean_prompt,
            }
            return "reminder", normalized_intent, execution_config

        # 8. General Computer / Workflow Automation
        normalized_intent = {
            "category": "general",
            "action": "execute_workflow",
        }
        execution_config = {
            "action_type": "automation",
            "clean_prompt_template": clean_prompt,
        }
        return "automation", normalized_intent, execution_config

    def _clean_schedule_prompt(self, prompt: str) -> str:
        """Strip command prefixes, trailing prepositions, and normalize prompt."""
        p = prompt.strip()
        p = re.sub(r"^\s*(?:schedule\s+(?:a\s+|an\s+)?|set\s+up\s+(?:a\s+|an\s+)?|create\s+(?:a\s+|an\s+)?(?:schedule|scheduled\s+task)\s+(?:to|for)?\s*|remind\s+me(?:\s+to)?|reminder\s+for|notify\s+me(?:\s+to)?)\s*", "", p, flags=re.IGNORECASE)
        p = re.sub(r"^\s*to\s+", "", p, flags=re.IGNORECASE)
        p = re.sub(r"\s+(?:for|on|at|by|to)\s*$", "", p, flags=re.IGNORECASE)
        p = p.strip(",:. ")
        if p.lower().startswith("email to "):
            p = "Send an " + p
        return p

    def _compute_task_name(self, clean_prompt: str, task_type: str, norm_intent: dict, default_name: str = "") -> str:
        """Generate human-readable task name from intent."""
        category = norm_intent.get("category", "")
        if category == "email":
            target = norm_intent.get("target") or "recipient"
            if "birthday" in clean_prompt.lower():
                return f"Send birthday email to {target}"
            return f"Send email to {target}"
        elif category == "research":
            topic = norm_intent.get("topic") or "topic"
            return f"Research report on {topic}"
        elif category == "research_doc":
            topic = norm_intent.get("topic") or "topic"
            return f"Research doc: {topic[:30]}"
        elif category == "spreadsheet":
            return "Weekly Excel report"
        elif category == "presentation":
            return "PowerPoint presentation"
        elif category == "code_check":
            return "Project error check"
        elif task_type == "reminder":
            return f"Reminder: {clean_prompt[:35]}"
        return clean_prompt[:40] if clean_prompt else default_name

    def parse_quick_rule(self, text: str, user_tz: Optional[str] = None) -> Optional[ScheduleParseResult]:
        """
        Fast deterministic rule-based parsing for standard recurring and one-time patterns.
        """
        tz_name = user_tz or self.default_tz
        tz = get_safe_timezone(tz_name)
        now = datetime.now(tz)
        raw = text.strip()
        lower = raw.lower()

        # Check for explicit reminder vs automation hints
        is_reminder_prefix = bool(re.search(r"^\s*(remind\s+me|reminder|notify\s+me|alert\s+me)\b", lower))

        # Exclude calendar events, meetings, and appointments so connector/agent handles them
        if re.search(r"\b(?:calendar|meeting|appointment)\b", lower) and not is_reminder_prefix:
            return None
        if re.search(r"\b(?:calendar\s+event|to\s+my\s+calendar|on\s+my\s+calendar|in\s+my\s+calendar|google\s+calendar)\b", lower):
            return None

        # Check for ambiguity: "remind me to ..." without any time/date indication
        time_keywords = [
            "at", "tomorrow", "today", "tonight", "every", "in", "am", "pm",
            "morning", "afternoon", "evening", "night", "monday", "tuesday",
            "wednesday", "thursday", "friday", "saturday", "sunday", "daily",
            "weekly", "monthly", "minute", "hour", "day", "january", "february",
            "march", "april", "may", "june", "july", "august", "september",
            "october", "november", "december"
        ]
        has_time_hint = any(re.search(r"\b" + kw + r"\b", lower) for kw in time_keywords)

        if is_reminder_prefix and not has_time_hint:
            prompt_match = re.search(r"^\s*(?:remind\s+me(?:\s+to)?|reminder\s+for|notify\s+me(?:\s+to)?)\s+(.+)", raw, re.IGNORECASE)
            prompt = prompt_match.group(1).strip() if prompt_match else raw
            return ScheduleParseResult(
                is_schedule=True,
                task_type="reminder",
                name=f"Reminder: {prompt[:30]}",
                prompt=prompt,
                schedule_type="one_time",
                timezone=tz_name,
                is_ambiguous=True,
                clarification_question=f"When would you like me to remind you to {prompt}?",
                confidence=0.85,
                normalized_intent={"category": "reminder"},
                execution_config={"action_type": "reminder", "clean_prompt_template": prompt},
            )

        # ---------------------------------------------------------------------
        # 1. Pattern: Specific Calendar Date:
        # "at <time> on <month> <day>" e.g. "Send John a happy birthday email at 12:00 AM on December 15."
        # "on <month> <day> at <time>" e.g. "On October 15 at 11:30 PM, send this email."
        # ---------------------------------------------------------------------
        cal_match = re.search(
            r"(?:at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+on\s+([a-zA-Z]+)\s+(\d{1,2})(?:st|nd|rd|th)?|"
            r"on\s+([a-zA-Z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))",
            lower
        )
        if cal_match:
            if cal_match.group(1) and cal_match.group(2) and cal_match.group(3):
                time_str = cal_match.group(1).strip()
                month_str = cal_match.group(2).strip().lower()
                day_num = int(cal_match.group(3))
            else:
                month_str = cal_match.group(4).strip().lower()
                day_num = int(cal_match.group(5))
                time_str = cal_match.group(6).strip()

            if month_str in MONTH_MAP and 1 <= day_num <= 31:
                month_num = MONTH_MAP[month_str]
                parsed_time = self._parse_time_str(time_str)
                h, m = map(int, parsed_time.split(":"))

                target_year = now.year
                try:
                    candidate = datetime(target_year, month_num, day_num, h, m, 0, tzinfo=tz)
                except ValueError:
                    candidate = datetime(target_year, month_num, min(day_num, 28), h, m, 0, tzinfo=tz)

                if candidate <= now:
                    try:
                        candidate = datetime(target_year + 1, month_num, day_num, h, m, 0, tzinfo=tz)
                    except ValueError:
                        candidate = datetime(target_year + 1, month_num, min(day_num, 28), h, m, 0, tzinfo=tz)

                # Clean prompt: strip temporal clause
                prompt = re.sub(
                    r"(?:at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+on\s+[a-zA-Z]+\s+\d{1,2}(?:st|nd|rd|th)?|"
                    r"on\s+[a-zA-Z]+\s+\d{1,2}(?:st|nd|rd|th)?\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
                    "",
                    raw,
                    flags=re.IGNORECASE
                ).strip()
                prompt = self._clean_schedule_prompt(prompt)

                task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
                computed_name = self._compute_task_name(prompt, task_type, norm_intent, f"{task_type.capitalize()} on {month_str.capitalize()} {day_num}")
                return ScheduleParseResult(
                    is_schedule=True,
                    task_type=task_type,
                    name=computed_name,
                    prompt=prompt or raw,
                    schedule_type="one_time",
                    schedule_definition={"frequency": "once", "target_time": candidate.isoformat()},
                    timezone=tz_name,
                    next_run_at=candidate,
                    confidence=0.98,
                    normalized_intent=norm_intent,
                    execution_config=exec_cfg,
                )

        # ---------------------------------------------------------------------
        # 2. Pattern: Specific Day of Week One-time:
        # "at <time> on <day_of_week>" e.g. "At 6 PM on Friday, create a PowerPoint presentation from this research."
        # "on <day_of_week> at <time>"
        # (Exclude if preceded by "every")
        # ---------------------------------------------------------------------
        if not re.search(r"\bevery\b", lower):
            dow_match = re.search(
                r"(?:at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b|"
                r"on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))",
                lower
            )
            if dow_match:
                if dow_match.group(1) and dow_match.group(2):
                    time_str = dow_match.group(1).strip()
                    day_str = dow_match.group(2).strip().lower()
                else:
                    day_str = dow_match.group(3).strip().lower()
                    time_str = dow_match.group(4).strip()

                parsed_time = self._parse_time_str(time_str)
                h, m = map(int, parsed_time.split(":"))
                target_weekday = WEEKDAY_MAP[day_str]
                days_ahead = (target_weekday - now.weekday()) % 7
                candidate_date = now.date() + timedelta(days=days_ahead)
                candidate = datetime.combine(candidate_date, time(h, m), tzinfo=tz)
                if candidate <= now:
                    candidate += timedelta(days=7)

                prompt = re.sub(
                    r"(?:at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)|"
                    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
                    "",
                    raw,
                    flags=re.IGNORECASE
                ).strip()
                prompt = re.sub(r"^\s*(?:remind\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s*", "", prompt, flags=re.IGNORECASE).strip()
                prompt = prompt.lstrip(",: ").rstrip(",: ").strip()

                task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
                return ScheduleParseResult(
                    is_schedule=True,
                    task_type=task_type,
                    name=prompt[:40] if prompt else f"{task_type.capitalize()} on {day_str.capitalize()}",
                    prompt=prompt or raw,
                    schedule_type="one_time",
                    schedule_definition={"frequency": "once", "target_time": candidate.isoformat()},
                    timezone=tz_name,
                    next_run_at=candidate,
                    confidence=0.96,
                    normalized_intent=norm_intent,
                    execution_config=exec_cfg,
                )

        # ---------------------------------------------------------------------
        # 3. Pattern: "in X minutes/hours"
        # ---------------------------------------------------------------------
        in_match = re.search(r"\bin\s+(\d+)\s*(mins?|minutes?|hours?|hrs?)\b", lower)
        if in_match:
            amount = int(in_match.group(1))
            unit = in_match.group(2)
            delta = timedelta(hours=amount) if "h" in unit else timedelta(minutes=amount)
            target_dt = now + delta
            prompt = re.sub(r"\bin\s+\d+\s*(?:mins?|minutes?|hours?|hrs?)\b", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"^\s*(?:remind\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s*", "", prompt, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"^\s*(?:to\s+)", "", prompt, flags=re.IGNORECASE).strip()
            prompt = prompt.lstrip(",: ").rstrip(",: ").strip()

            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
            return ScheduleParseResult(
                is_schedule=True,
                task_type=task_type,
                name=f"{task_type.capitalize()}: {prompt[:30]}",
                prompt=prompt or raw,
                schedule_type="one_time",
                schedule_definition={"frequency": "once", "target_time": target_dt.isoformat()},
                timezone=tz_name,
                next_run_at=target_dt,
                confidence=0.95,
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )

        # ---------------------------------------------------------------------
        # 4. Pattern: "every weekday at <time>"
        # ---------------------------------------------------------------------
        weekday_match = re.search(r"every\s+weekday\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", lower)
        if weekday_match:
            time_part = weekday_match.group(1).strip()
            parsed_time = self._parse_time_str(time_part)
            prompt = re.sub(r"every\s+weekday\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"^(?:run\s+this\s+task\s+|check\s+and\s+|to\s+)?", "", prompt, flags=re.IGNORECASE).strip(", ")
            prompt = re.sub(r"^\s*(?:remind\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s*", "", prompt, flags=re.IGNORECASE).strip()
            prompt = prompt.lstrip(",: ").rstrip(",: ").strip()

            schedule_def = {"frequency": "weekdays", "time": parsed_time}
            next_run = calculate_next_run("recurring", schedule_def, tz_name, now)
            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
            return ScheduleParseResult(
                is_schedule=True,
                task_type=task_type,
                name=prompt[:40] if prompt else "Weekday automation",
                prompt=prompt or raw,
                schedule_type="recurring",
                schedule_definition=schedule_def,
                timezone=tz_name,
                next_run_at=next_run,
                confidence=0.95,
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )

        # ---------------------------------------------------------------------
        # 5. Pattern: "every (day|morning|afternoon|evening|night) at <time>"
        # e.g. "Every day at 8 AM, research the latest news about my project and create a summary."
        # e.g. "Every morning at 9 AM, check my project and tell me if there are any errors."
        # ---------------------------------------------------------------------
        daily_match = re.search(r"every\s+(?:day|morning|afternoon|evening|night)?\s*at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", lower)
        if daily_match:
            time_part = daily_match.group(1).strip()
            parsed_time = self._parse_time_str(time_part)
            prompt = re.sub(r"every\s+(?:day|morning|afternoon|evening|night)?\s*at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"^\s*(?:remind\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s*", "", prompt, flags=re.IGNORECASE).strip()
            prompt = prompt.lstrip(",: ").rstrip(",: ").strip()

            schedule_def = {"frequency": "daily", "time": parsed_time}
            next_run = calculate_next_run("recurring", schedule_def, tz_name, now)
            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
            return ScheduleParseResult(
                is_schedule=True,
                task_type=task_type,
                name=prompt[:40] if prompt else "Daily task",
                prompt=prompt or raw,
                schedule_type="recurring",
                schedule_definition=schedule_def,
                timezone=tz_name,
                next_run_at=next_run,
                confidence=0.95,
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )

        # ---------------------------------------------------------------------
        # 6. Pattern: "every <day_of_week> at <time>"
        # e.g. "Every Monday at 9 AM, create my weekly Excel report."
        # ---------------------------------------------------------------------
        weekly_match = re.search(r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", lower)
        if weekly_match:
            day_name = weekly_match.group(1).strip()
            time_part = weekly_match.group(2).strip()
            norm_day = REVERSE_WEEKDAY_MAP[WEEKDAY_MAP[day_name]]
            parsed_time = self._parse_time_str(time_part)
            prompt = re.sub(r"every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"^\s*(?:remind\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s*", "", prompt, flags=re.IGNORECASE).strip()
            prompt = prompt.lstrip(",: ").rstrip(",: ").strip()

            schedule_def = {"frequency": "weekly", "days": [norm_day], "time": parsed_time}
            next_run = calculate_next_run("recurring", schedule_def, tz_name, now)
            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
            return ScheduleParseResult(
                is_schedule=True,
                task_type=task_type,
                name=prompt[:40] if prompt else f"Weekly {norm_day} task",
                prompt=prompt or raw,
                schedule_type="recurring",
                schedule_definition=schedule_def,
                timezone=tz_name,
                next_run_at=next_run,
                confidence=0.95,
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )

        # ---------------------------------------------------------------------
        # 7. Pattern: "tomorrow at <time>", "for tomorrow at <time>", "at <time> tomorrow"
        # e.g. "Schedule a research report on AI agents for tomorrow at 6 PM."
        # e.g. "Tomorrow at 8 AM, research the latest developments in AI agents and create a Word document."
        # e.g. "Remind me tomorrow at 6 PM to submit my project."
        # ---------------------------------------------------------------------
        day_time_match = re.search(r"(?:for\s+)?(tomorrow|today)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", lower)
        day_keyword = None
        time_part = None
        if day_time_match:
            day_keyword = day_time_match.group(1)
            time_part = day_time_match.group(2).strip()
        else:
            time_day_match = re.search(r"at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:for\s+)?(tomorrow|today)", lower)
            if time_day_match:
                time_part = time_day_match.group(1).strip()
                day_keyword = time_day_match.group(2)

        if day_keyword and time_part:
            parsed_time = self._parse_time_str(time_part)
            h, m = map(int, parsed_time.split(":"))
            target_date = now.date() if day_keyword == "today" else now.date() + timedelta(days=1)
            target_dt = datetime.combine(target_date, time(h, m), tzinfo=tz)
            if day_keyword == "today" and target_dt <= now:
                target_dt += timedelta(days=1)

            prompt = re.sub(r"(?:for\s+)?(?:tomorrow|today)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+(?:for\s+)?(?:tomorrow|today)", "", prompt, flags=re.IGNORECASE).strip()
            prompt = self._clean_schedule_prompt(prompt)

            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(prompt, raw, is_reminder_prefix)
            computed_name = self._compute_task_name(prompt, task_type, norm_intent, f"{task_type.capitalize()} task")
            return ScheduleParseResult(
                is_schedule=True,
                task_type=task_type,
                name=computed_name,
                prompt=prompt or raw,
                schedule_type="one_time",
                schedule_definition={"frequency": "once", "target_time": target_dt.isoformat()},
                timezone=tz_name,
                next_run_at=target_dt,
                confidence=0.95,
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )

        # ---------------------------------------------------------------------
        # 8. Ambiguity: "remind me tomorrow to ..." without explicit time
        # ---------------------------------------------------------------------
        if re.search(r"\btomorrow\b", lower) and not re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", lower):
            prompt = re.sub(r"^\s*(?:remind\s+me|notify\s+me)\s+(?:tomorrow\s+)?(?:to\s+)?", "", raw, flags=re.IGNORECASE).strip()
            prompt = re.sub(r"\btomorrow\b", "", prompt, flags=re.IGNORECASE).strip()
            prompt = prompt.lstrip(",: ").rstrip(",: ").strip()
            return ScheduleParseResult(
                is_schedule=True,
                task_type="reminder" if is_reminder_prefix else "automation",
                name=f"Reminder: {prompt[:30]}",
                prompt=prompt or raw,
                schedule_type="one_time",
                timezone=tz_name,
                is_ambiguous=True,
                clarification_question="What time tomorrow should I trigger this (e.g. 9:00 AM or 6:00 PM)?",
                confidence=0.88,
                normalized_intent={"category": "reminder"},
                execution_config={"action_type": "reminder", "clean_prompt_template": prompt},
            )

        return None

    def _parse_time_str(self, time_str: str) -> str:
        """Helper to parse strings like '9 am', '8:30 pm', '12:00 am', '12:00 pm', '18:00', '9' into 'HH:MM' (24hr)."""
        time_str = time_str.strip().lower()
        is_pm = "pm" in time_str
        is_am = "am" in time_str
        clean = re.sub(r"[^\d:]", "", time_str)
        if ":" in clean:
            parts = clean.split(":")
            h, m = int(parts[0]), int(parts[1])
        else:
            h, m = int(clean) if clean else 9, 0

        if is_pm and h < 12:
            h += 12
        elif is_am and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    async def parse(self, text: str, user_tz: Optional[str] = None) -> ScheduleParseResult:
        """
        Main parser entry point. Tries quick deterministic rules first.
        If uncertain, falls back to LLM structured parser.
        """
        tz_name = user_tz or self.default_tz
        rule_result = self.parse_quick_rule(text, tz_name)
        if rule_result is not None:
            return rule_result

        # Check if text appears to contain scheduling intent at all
        schedule_keywords = [
            "schedule", "remind", "reminder", "every day", "every morning",
            "every week", "every month", "recurring", "cron", "timer",
            "at 9", "at 10", "at 8", "tomorrow at", "run every", "at 12", "at 6"
        ]
        has_keywords = any(kw in text.lower() for kw in schedule_keywords)
        if not has_keywords:
            return ScheduleParseResult(is_schedule=False)

        # Fallback to LLM parser
        return await self._parse_with_llm(text, tz_name)

    async def _parse_with_llm(self, text: str, tz_name: str) -> ScheduleParseResult:
        """Structured LLM extraction fallback for complex natural language expressions."""
        from backend.agent.router.model_router import ainvoke_with_dynamic_switch
        from langchain_core.messages import SystemMessage, HumanMessage

        tz = get_safe_timezone(tz_name)
        now = datetime.now(tz)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S (%A, %Z)")

        system_prompt = f"""You are N.E.X.U.S. Schedule Engine.
Current User Local Time: {now_str} (Timezone: {tz_name}).

Analyze the user's input to determine if it is a request to schedule a task or set a reminder.
Respond ONLY with a valid JSON object matching this schema:
{{
  "is_schedule": true/false,
  "task_type": "reminder" or "automation",
  "name": "Short 3-6 word task title",
  "prompt": "Clean actionable command or reminder text",
  "schedule_type": "one_time" or "recurring",
  "schedule_definition": {{
      "frequency": "once" | "daily" | "weekdays" | "weekly" | "monthly" | "interval",
      "target_time": "ISO-8601 string if once, e.g. 2026-10-02T18:00:00",
      "time": "HH:MM (24-hr) for daily/weekly/monthly/weekdays",
      "days": ["monday", ...] for weekly,
      "day_of_month": 1..31 for monthly,
      "interval_minutes": 60 for interval
  }},
  "is_ambiguous": true/false,
  "clarification_question": "string or null if information like time or day is missing",
  "confidence": 0.0 - 1.0
}}

Guidelines:
- "reminder": simple notifications, e.g. "remind me to take medicine", "remind me at 6pm to submit project".
- "automation": computer/workflow actions to execute, e.g. "every day at 9am check my project for errors", "generate weekly report every monday".
- If time or date is unspecified (e.g. "remind me to check mail"), set is_ambiguous=true and provide clarification_question.
- Do not output markdown codeblocks (no ```json). Output raw JSON.
"""

        try:
            response = await ainvoke_with_dynamic_switch(
                task_type="fast",
                messages=[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=text),
                ],
                temperature=0.0,
            )
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)

            sched_type = data.get("schedule_type", "one_time")
            sched_def = data.get("schedule_definition") or {}
            next_run = None
            if not data.get("is_ambiguous", False):
                next_run = calculate_next_run(sched_type, sched_def, tz_name, now)

            clean_p = data.get("prompt", text)
            task_type = data.get("task_type", "reminder")
            task_type, norm_intent, exec_cfg = self._extract_automation_metadata(clean_p, text, is_explicit_reminder=(task_type == "reminder"))

            return ScheduleParseResult(
                is_schedule=bool(data.get("is_schedule", True)),
                task_type=task_type,
                name=data.get("name", text[:30]),
                prompt=clean_p,
                schedule_type=sched_type,
                schedule_definition=sched_def,
                timezone=tz_name,
                next_run_at=next_run,
                is_ambiguous=bool(data.get("is_ambiguous", False)),
                clarification_question=data.get("clarification_question"),
                confidence=float(data.get("confidence", 0.8)),
                normalized_intent=norm_intent,
                execution_config=exec_cfg,
            )
        except Exception as exc:
            logger.warning("LLM schedule parsing failed: %s", exc)
            return ScheduleParseResult(is_schedule=False)


schedule_parser = ScheduleParser()
