"""Planner node — generates structured multi-step execution plans."""
from __future__ import annotations
import json
import logging
import uuid
from langchain_core.messages import SystemMessage, HumanMessage
from backend.agent.state import NexusState, PlanStep
from backend.agent.router.model_router import ainvoke_with_dynamic_switch
from backend.core.config import get_groq_api_key, get_gemma_api_key
from backend.core.policies import RiskLevel, classify_command, classify_file_op

logger = logging.getLogger("nexus.planner")


async def _compose_smart_email(goal: str, to_email: str, sender_name: Optional[str] = None) -> tuple[str, str]:
    """Composes a high-quality subject and body for an email action.
    Uses fast LLM (<500ms) with clean deterministic heuristic fallback."""
    import re
    import json
    import asyncio

    # Determine sender name:
    # 1. Prompt override takes highest priority if explicitly specified:
    # e.g., "from Bob", "sign off as Alice", "sender name is Charlie", "signed John", "send from Sarah"
    stop_words = {"regarding", "about", "subject", "saying", "body", "to", "for", "how", "on", "with", "that", "message", "content", "and", "but", "or", "myself", "me", "my", "email", "gmail", "nexus"}
    explicit_sender_match = re.search(
        r"\b(?:send\s+)?(?:from|signed|sign\s+(?:off\s+)?as|sender(?:\s+name)?(?:\s+is)?[:\s]+)\s+([a-zA-Z]{2,25})(?:\s+([a-zA-Z]{2,25}))?\b",
        goal,
        re.IGNORECASE,
    )
    if explicit_sender_match:
        w1 = explicit_sender_match.group(1).strip()
        w2 = explicit_sender_match.group(2).strip() if explicit_sender_match.group(2) else None
        if w1.lower() not in stop_words:
            if w2 and w2.lower() not in stop_words:
                effective_sender = f"{w1.capitalize()} {w2.capitalize()}"
            else:
                effective_sender = w1.capitalize()
        else:
            effective_sender = sender_name or "NEXUS Assistant"
    else:
        effective_sender = sender_name or "NEXUS Assistant"

    placeholder_pattern = r"\[(?:Your Name|Sender Name|Sender|Name|My Name|User Name|Insert Name)\]"

    # 1. Fast LLM attempt if API key is configured
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from backend.agent.router.model_router import ainvoke_with_dynamic_switch

        sys_prompt = (
            "You are an expert AI email composer for the NEXUS assistant.\n"
            "Given the user request, compose a clear, well-structured, context-appropriate email.\n"
            f"The sender's name is: '{effective_sender}'.\n"
            "Rules:\n"
            "1. Output ONLY a valid JSON object: {\"subject\": \"<concise subject>\", \"body\": \"<email body>\"}\n"
            "2. The body MUST include an appropriate polite greeting, well-formatted paragraphs, and a clean professional sign-off.\n"
            f"3. Sign off using '{effective_sender}' (or the sender name explicitly specified in the user request). NEVER output placeholder text like '[Your Name]' or '[Sender]'.\n"
            "4. NEVER copy the user's raw prompt or instructions like 'send a mail to...' into the subject or body.\n"
            "5. Keep the subject line concise (under 8 words).\n"
            "6. If user included specific text in quotes, incorporate and polish that message."
        )

        res = await asyncio.wait_for(
            ainvoke_with_dynamic_switch(
                [SystemMessage(content=sys_prompt), HumanMessage(content=goal)],
                operation="fast",
                temperature=0.2,
            ),
            timeout=3.0,
        )

        raw_content = res.content.strip()
        if "```" in raw_content:
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:].strip()
            raw_content = raw_content.strip()
        data = json.loads(raw_content)
        sub = data.get("subject", "").strip()
        bod = data.get("body", "").strip()
        if sub and bod:
            bod = re.sub(placeholder_pattern, effective_sender, bod, flags=re.IGNORECASE)
            return sub, bod
    except Exception as exc:
        logger.debug("Fast LLM email composition fallback: %s", exc)

    # 2. Smart Deterministic Heuristic Fallback
    sub_match = re.search(r"(?:subject|regarding|about|title)[:\s]+[\"']?([^\"'\n]+)[\"']?", goal, re.IGNORECASE)
    quotes_match = re.search(r"[\"']([^\"']{2,})[\"']", goal)
    body_kw_match = re.search(r"(?:body|saying|message|content)[:\s]+[\"']?(.+?)(?:[\"']|\s+(?:subject|regarding|about)\b|$)", goal, re.IGNORECASE)

    raw_msg = ""
    if body_kw_match:
        raw_msg = body_kw_match.group(1).strip()
    elif quotes_match:
        raw_msg = quotes_match.group(1).strip()

    if raw_msg:
        if sub_match:
            subject = sub_match.group(1).strip()
        else:
            words = [w for w in re.split(r"\s+", raw_msg) if w]
            subject = " ".join(words[:5]).strip(".,!?") if words else "Message from NEXUS"
            if not subject:
                subject = "Quick Note"

        has_greeting = any(raw_msg.lower().startswith(g) for g in ("hi", "hello", "hey", "dear"))
        has_signoff = any(s in raw_msg.lower() for s in ("regards", "thanks", "best", "sincerely", "cheers"))

        parts = []
        if not has_greeting:
            parts.append("Hi,")
        parts.append(raw_msg)
        if not has_signoff:
            parts.append(f"Best regards,\n{effective_sender}")
        body = "\n\n".join(parts)
        body = re.sub(placeholder_pattern, effective_sender, body, flags=re.IGNORECASE)
        return subject, body

    # Fallback when no quotes or body keyword found: strip command boilerplate
    cleaned = re.sub(r"(?i)\b(send|compose|write|dispatch|draft)\s+(an?\s+)?(mail|email)\s+(to\s+[^\s]+\s+)?", "", goal).strip()
    cleaned = cleaned.strip("\"' ")
    subject = sub_match.group(1).strip() if sub_match else (cleaned[:40].title() if cleaned else "Message from NEXUS")
    body = f"Hello,\n\n{cleaned or 'Hope you are doing well.'}\n\nBest regards,\n{effective_sender}"
    body = re.sub(placeholder_pattern, effective_sender, body, flags=re.IGNORECASE)
    return subject, body


async def _build_active_connector_priority_plan(goal: str, user_id: str = "default", raw_input: str = "", user_name: Optional[str] = None) -> list[dict]:
    """Prefer connected API/MCP connectors over browser or desktop automation."""
    lower = (goal or "").lower().strip()
    if not lower and not raw_input:
        return []

    try:
        from backend.agent.tools.registry import tool_registry
        from backend.connectors.credentials_store import credentials_store
        from backend.connectors.manager import connector_manager
        from backend.connectors.catalog import get_connector_definition
        from backend.connectors.tool_wrapper import ConnectorTool
        from backend.connectors.models import ConnectorToolMetadata
    except Exception:
        return []

    connector_matches = [
        ("gmail", ["gmail", "google mail", "email", "mail"], ["gmail_send_email", "gmail_create_draft"]),
        ("google_calendar", ["calendar", "meeting", "schedule", "event"], ["calendar_create_event", "calendar_list_events", "calendar_delete_event"]),
        ("spotify", ["spotify", "music", "song", "playlist", "track", "play"], ["spotify_play_track", "spotify_search_tracks"]),
        ("slack", ["slack", "channel", "message"], ["slack_send_message"]),
        ("todoist", ["todoist", "todo", "task"], ["todoist_create_task", "todoist_list_tasks"]),
        ("linear", ["linear", "issue", "ticket", "sprint"], ["linear_create_issue", "linear_search_issues"]),
        ("notion", ["notion", "page", "document"], ["notion_search_pages"]),
        ("github", ["github", "repo", "repository", "issue", "pull request", "commit"], ["github_create_issue", "github_search_repositories"]),
        ("google_drive", ["drive", "google drive", "gdrive", "docs", "sheets", "cloud file", "drive file"], ["drive_search_files", "drive_get_file"]),
        ("filesystem", ["file", "folder", "directory", "desktop", "read", "write", "save", "open"], ["read_file", "write_file", "list_directory", "search_files"]),
    ]

    for connector_id, keywords, tool_names in connector_matches:
        if connector_id == "filesystem" and any(w in lower for w in ("excel", "xlsx", "spreadsheet", "csv", "docx", "word doc", "word document", "word file", "word report", "word", "document", "powerpoint", "presentation", "slides", "ppt")):
            continue
        if not any(keyword in lower for keyword in keywords):
            continue

        creds = credentials_store.get_credential(user_id or "default", connector_id)
        if not creds:
            creds = credentials_store.get_credential("default", connector_id)

        # If credentials exist but tools are not yet in registry (e.g. fresh worker process), register them now
        if creds and not any(tool_registry.has(name) for name in tool_names):
            adapter = connector_manager.get_adapter(connector_id)
            defn = get_connector_definition(connector_id)
            if adapter and defn:
                for dt in (getattr(defn, "default_tools", None) or tool_names):
                    clean_name = dt.replace(f"{connector_id}_", "")
                    meta = ConnectorToolMetadata(
                        tool_id=f"{connector_id}.{clean_name}",
                        connector_id=connector_id,
                        name=dt,
                        description=f"{defn.name} tool {clean_name}",
                        risk_level="PRIVILEGED" if "send" in dt else ("caution" if any(w in dt for w in ("write", "create", "delete")) else "safe"),
                        source="api",
                        input_schema={"type": "object", "properties": {}},
                    )
                    tool_registry.register(ConnectorTool(meta, adapter, user_id or "default"))

        preferred_tool = next((name for name in tool_names if tool_registry.has(name)), None)
        if not preferred_tool:
            continue

        if connector_id == "gmail":
            import re
            account_email = (creds.get("account_identifier") if creds else None) or "sagnify2022@gmail.com"

            to_match = re.search(r"\bto\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9_]+)\b", goal, re.IGNORECASE)
            email_anywhere = re.search(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", goal)
            raw_to = (to_match.group(1) if to_match else (email_anywhere.group(0) if email_anywhere else account_email)).strip()

            # Handle "to myself", "to me", "self"
            if raw_to.lower() in ("myself", "me", "self", "my email", "mine") or not raw_to:
                to_email = account_email
            else:
                to_email = raw_to

            # Resolve sender name from user_name or Gmail credentials or OS
            sender = user_name
            if not sender and creds:
                sender = creds.get("display_name") or creds.get("name")
                if not sender and creds.get("account_identifier"):
                    prefix = creds["account_identifier"].split("@")[0]
                    clean = re.sub(r"\d+", "", prefix).strip("._- ")
                    sender = clean.capitalize() if len(clean) >= 2 else prefix.capitalize()
            if not sender:
                import os
                os_user = os.environ.get("USERNAME") or os.environ.get("USER")
                if os_user:
                    sender = os_user.capitalize()

            subject_text, body_text = await _compose_smart_email(goal, to_email, sender_name=sender)

            tool = preferred_tool
            risk_lvl = "PRIVILEGED"
            if any(w in lower for w in ("save as draft", "save draft", "to drafts")) and tool_registry.has("gmail_create_draft"):
                tool = "gmail_create_draft"
                risk_lvl = "SAFE"
            elif tool_registry.has("gmail_send_email"):
                tool = "gmail_send_email"
                risk_lvl = "PRIVILEGED"

            return [{
                "title": f"Send email to {to_email} via Gmail API",
                "description": f"Send email '{subject_text}' to {to_email}",
                "tool": tool,
                "args": {"to": to_email, "subject": subject_text, "body": body_text},
                "risk_level": risk_lvl,
            }]
        if connector_id == "google_calendar":
            import datetime
            import re
            from zoneinfo import ZoneInfo
            combined_text = f"{(raw_input or '').lower()} {lower}"

            # 1. Delete / Cancel Event
            is_delete = any(w in combined_text for w in ("delete", "cancel", "remove", "drop")) and any(w in combined_text for w in ("calendar", "meeting", "event", "appointment"))
            if is_delete and tool_registry.has("calendar_delete_event"):
                id_match = re.search(r"\b(?:id|event_id)[:\s]+([a-zA-Z0-9_-]{10,})\b", goal, re.IGNORECASE)
                event_id_val = id_match.group(1) if id_match else None

                del_title_match = re.search(r"(?:delete|cancel|remove)\s+(?:calendar\s+)?(?:event|meeting|appointment)?\s*(?:called|named|titled|for)?\s*['\"]?([^'\"\n,]+)['\"]?", goal, re.IGNORECASE)
                del_target = del_title_match.group(1).strip() if del_title_match else goal

                return [{
                    "title": f"Cancel Calendar Event: {del_target[:50]}",
                    "description": "Delete event directly via Google Calendar API without browser automation.",
                    "tool": "calendar_delete_event",
                    "args": {"event_id": event_id_val, "summary": del_target if not event_id_val else None},
                }]

            # 2. Queries that mean reading, listing, or viewing schedule or events
            is_read = any(w in combined_text for w in (
                "what", "list", "show", "check", "view", "get", "read", "see",
                "any", "events", "meetings", "retrieve", "display", "find",
                "agenda", "upcoming", "my schedule", "today's schedule", "todays schedule", "calendar"
            )) and not any(w in combined_text for w in (
                "create", "add", "schedule a", "schedule an", "new event", "new meeting", "set up a", "set up an", "book a", "book an"
            ))

            is_create = not is_read and any(w in combined_text for w in (
                "create", "add", "schedule a", "schedule an", "new event", "new meeting",
                "set up a", "set up an", "book a", "book an", "make an appointment", "schedule"
            ))

            if is_create and tool_registry.has("calendar_create_event"):
                quoted = re.search(r"['\"]([^'\"]+)['\"]", goal)
                if quoted:
                    event_summary = quoted.group(1).strip()
                else:
                    named_match = re.search(r"(?:called|named|titled|for|summary)\s+['\"]?(.+?)(?:['\"]|\s+(?:tomorrow|today|on|at|with|from)\b|$)", goal, re.IGNORECASE)
                    if named_match:
                        event_summary = named_match.group(1).strip()
                    else:
                        clean_goal = re.sub(r"^(?:create|schedule|add|set up|book)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:calendar\s+)?(?:event|meeting|appointment)?\s*(?:called|named|titled|for)?\s*", "", goal, flags=re.IGNORECASE)
                        clean_goal = re.sub(r"\s+(?:tomorrow|today|on\s+\d|at\s+\d|with\s+\S+@).*", "", clean_goal, flags=re.IGNORECASE)
                        event_summary = clean_goal.strip() or goal

                attendee_emails = re.findall(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", goal)

                user_tz = ZoneInfo("Asia/Kolkata")
                now_dt = datetime.datetime.now(user_tz)
                target_date = now_dt.date()

                iso_date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", goal)
                if iso_date_match:
                    try:
                        target_date = datetime.date.fromisoformat(iso_date_match.group(1))
                    except Exception:
                        pass
                elif "tomorrow" in lower:
                    target_date = now_dt.date() + datetime.timedelta(days=1)

                time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", goal, re.IGNORECASE)
                if time_match:
                    hr = int(time_match.group(1))
                    mn = int(time_match.group(2) or 0)
                    ampm = (time_match.group(3) or "").lower()
                    if ampm == "pm" and hr < 12:
                        hr += 12
                    elif ampm == "am" and hr == 12:
                        hr = 0
                    start_dt = datetime.datetime.combine(target_date, datetime.time(hr, mn), tzinfo=user_tz)
                else:
                    start_dt = (now_dt + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

                end_dt = start_dt + datetime.timedelta(hours=1)
                start_iso = start_dt.isoformat()
                end_iso = end_dt.isoformat()

                args_payload = {
                    "summary": event_summary,
                    "start_time": start_iso,
                    "end_time": end_iso,
                }
                if attendee_emails:
                    args_payload["attendees"] = attendee_emails

                return [{
                    "title": f"Create Calendar Event: {event_summary[:50]}",
                    "description": "Schedule event directly via Google Calendar API without browser automation.",
                    "tool": "calendar_create_event",
                    "args": args_payload,
                }]
            else:
                user_tz = ZoneInfo("Asia/Kolkata")
                now_dt = datetime.datetime.now(user_tz)
                q_match = re.search(r"(?:for|about|matching|named|called)\s+['\"]?([^'\"\n]+)['\"]?", goal, re.IGNORECASE)
                query_val = q_match.group(1).strip() if q_match and any(w in lower for w in ("search", "find", "check for")) else None
                args_payload = {"max_results": 10}
                if query_val:
                    args_payload["query"] = query_val

                is_today = any(w in combined_text for w in ("today", "today's", "todays", "tonight", "this morning", "this afternoon", "this evening"))
                is_tomorrow = "tomorrow" in combined_text

                if is_today:
                    start_today = datetime.datetime.combine(now_dt.date(), datetime.time.min, tzinfo=user_tz)
                    end_today = datetime.datetime.combine(now_dt.date(), datetime.time.max, tzinfo=user_tz)
                    args_payload["time_min"] = start_today.isoformat()
                    args_payload["time_max"] = end_today.isoformat()
                    title_text = "Check Today's Schedule via Google Calendar API"
                    desc_text = "Retrieve only today's schedule and events directly through Google Calendar API."
                elif is_tomorrow:
                    tomorrow_date = now_dt.date() + datetime.timedelta(days=1)
                    start_tomorrow = datetime.datetime.combine(tomorrow_date, datetime.time.min, tzinfo=user_tz)
                    end_tomorrow = datetime.datetime.combine(tomorrow_date, datetime.time.max, tzinfo=user_tz)
                    args_payload["time_min"] = start_tomorrow.isoformat()
                    args_payload["time_max"] = end_tomorrow.isoformat()
                    title_text = "Check Tomorrow's Schedule via Google Calendar API"
                    desc_text = "Retrieve only tomorrow's schedule and events directly through Google Calendar API."
                else:
                    title_text = "Check Calendar Events via Google Calendar API"
                    desc_text = "Retrieve upcoming events directly through Google Calendar API without browser automation."

                return [{
                    "title": title_text,
                    "description": desc_text,
                    "tool": "calendar_list_events",
                    "args": args_payload,
                }]
        if connector_id == "spotify":
            clean_track = re.sub(r"\b(?:play|song|music|track|on|from|spotify)\b", "", goal, flags=re.IGNORECASE).strip() or goal
            return [{
                "title": f"Play on Spotify: {clean_track[:50]}",
                "description": "Control playback directly via Spotify API without desktop automation.",
                "tool": "spotify_play_track",
                "args": {"query": clean_track},
            }]
        if connector_id == "slack":
            clean_text = re.sub(r"\b(?:send|message|slack|saying|text|to)\b", "", goal, flags=re.IGNORECASE).strip() or goal
            return [{
                "title": "Send message via Slack API",
                "description": "Use the connected Slack connector instead of browser automation.",
                "tool": preferred_tool,
                "args": {"channel": "general", "text": clean_text},
            }]
        if connector_id == "todoist":
            is_list = any(w in lower for w in ("list", "show", "get", "view", "tasks", "todos")) and not any(w in lower for w in ("add", "create", "new", "make"))
            if is_list and tool_registry.has("todoist_list_tasks"):
                return [{
                    "title": "List Todoist Tasks",
                    "description": "Retrieve tasks directly via Todoist API.",
                    "tool": "todoist_list_tasks",
                    "args": {},
                }]
            else:
                clean_task = re.sub(r"\b(?:add|create|new|task|todo|to|in|todoist)\b", "", goal, flags=re.IGNORECASE).strip() or goal
                return [{
                    "title": f"Add Todoist Task: {clean_task[:50]}",
                    "description": "Add task directly via Todoist API.",
                    "tool": "todoist_create_task",
                    "args": {"content": clean_task, "due_string": "today"},
                }]
        if connector_id == "linear":
            is_list = any(w in lower for w in ("list", "search", "show", "find", "issues", "tickets")) and not any(w in lower for w in ("create", "add", "new", "make"))
            if is_list and tool_registry.has("linear_search_issues"):
                return [{
                    "title": "Search Linear Issues",
                    "description": "Search sprint issues directly via Linear API.",
                    "tool": "linear_search_issues",
                    "args": {"query": goal},
                }]
            else:
                return [{
                    "title": f"Create Linear Issue: {goal[:60]}",
                    "description": "Create issue directly via Linear API.",
                    "tool": "linear_create_issue",
                    "args": {"title": goal[:80], "description": goal},
                }]
        if connector_id == "notion":
            return [{
                "title": f"Search Notion: {goal[:50]}",
                "description": "Search workspace pages directly via Notion API.",
                "tool": "notion_search_pages",
                "args": {"query": goal},
            }]
        if connector_id == "github":
            is_issue = any(w in lower for w in ("issue", "ticket", "bug"))
            is_create = any(w in lower for w in ("create", "new", "open", "file", "make", "add"))
            if is_issue and is_create and tool_registry.has("github_create_issue"):
                return [{
                    "title": f"Create GitHub Issue: {goal[:60]}",
                    "description": "Create repository issue directly via GitHub API/MCP.",
                    "tool": "github_create_issue",
                    "args": {"title": goal[:80], "body": f"Automated issue from NEXUS: {goal}"},
                }]
            else:
                return [{
                    "title": f"Search GitHub: {goal[:50]}",
                    "description": "Search GitHub repositories directly via API/MCP.",
                    "tool": "github_search_repositories",
                    "args": {"query": goal},
                }]
        if connector_id == "google_drive":
            clean_q = re.sub(r"\b(?:search|find|look for|get|open|show|in|on|google drive|drive|gdrive|files?)\b", "", goal, flags=re.IGNORECASE).strip() or goal
            return [{
                "title": f"Search Google Drive: {clean_q[:50]}",
                "description": "Search files directly through Google Drive API without opening Chrome.",
                "tool": "drive_search_files",
                "args": {"query": clean_q},
            }]
        if connector_id == "filesystem":
            tool = "read_file" if any(k in lower for k in ("read", "open", "show", "inspect")) else "write_file" if any(k in lower for k in ("write", "save", "create")) else "list_directory"
            args = {"path": "."}
            if tool in ("read_file", "write_file"):
                args["path"] = "./"
            return [{
                "title": "Use filesystem connector",
                "description": "Use the connected filesystem API before desktop automation.",
                "tool": tool,
                "args": args,
            }]

    return []

PLANNER_PROMPT = """You are NEXUS's Strategic Execution Planner.
NEXUS is an autonomous execution agent running on the host operating system (Windows).
Your primary mandate is REAL ACTION AND DIRECT EXECUTION — NEVER conversational tutorial manuals, bash/batch scripts, or passive instructional steps.

PRINCIPLE: Intent first, mechanism second.
For browser and web tasks: Browser/CDP -> live DOM -> structured interaction.
Only fall back to OCR -> VLM -> GUI automation when the required state or interaction cannot reliably be accessed through the DOM/browser APIs (such as canvas games or OS desktop windows).

EXECUTION HIERARCHY:
0. TIER 0 (HIGHEST PRIORITY - CONNECTED APPLICATION CONNECTORS & MCP APIs):
   - Whenever the user asks to interact with an external service (e.g. Gmail, Google Calendar, Google Drive, GitHub, Slack, Spotify, Todoist, Linear, Notion, or any active MCP tool):
   - If a corresponding tool is listed in "Connected Application Connectors & Active MCP Tools", YOU MUST ALWAYS USE THAT CONNECTOR TOOL!
   - Connector tools execute directly via official authenticated APIs in milliseconds without opening browser tabs, navigating websites, or driving the user's mouse/keyboard.
   - NEVER use structured browser automation (`browser_navigate`, `browser_click`, etc.) for any task where an active connector tool exists!
   - ONLY fall back to Browser/Web Automation if NO connector tool exists or is connected for the requested service.

1. TIER 1 (PRIMARY FOR LOCAL SYSTEM): Shell, System CLI & Filesystem Execution
   - Direct system commands or file APIs (`run_command`, `write_file`, `read_file`, `delete_file`, `list_directory`, `search_files`).

2. TIER 1.5 (FALLBACK FOR UNCONNECTED WEB SITES): CDP & Live DOM (NO VLM)
   - Use structured browser tools for web browsing, web forms, clicking web buttons, reading page content, web scraping, and web interactions ONLY when no direct connector API is available.
   - Fast, deterministic, and interacts directly with the live DOM without screenshot or visual grounding delays!
   - Structured Browser Workflow Example ("Open example.com and search for NEXUS"):
     [
       {"title": "Navigate to Website", "description": "Navigate browser to target URL", "tool": "browser_navigate", "args": {"url": "https://example.com"}},
       {"title": "Inspect Page Elements", "description": "Inspect live DOM and retrieve interactive buttons/inputs", "tool": "browser_inspect", "args": {}},
       {"title": "Type Query", "description": "Type search term into search box and press Enter", "tool": "browser_type", "args": {"selector": "input[name='q']", "text": "NEXUS", "press_enter": true}},
       {"title": "Wait for Page", "description": "Wait for results page to settle", "tool": "browser_wait", "args": {"timeout_seconds": 2.0}},
       {"title": "Inspect Results", "description": "Inspect updated search results", "tool": "browser_inspect", "args": {}}
     ]
   - Structured Browser Form Example ("Fill login form on example.com"):
     [
       {"title": "Navigate to Login", "description": "Open login page", "tool": "browser_navigate", "args": {"url": "https://example.com/login"}},
       {"title": "Inspect Form", "description": "Extract form input selectors", "tool": "browser_inspect", "args": {}},
       {"title": "Enter Email", "description": "Type user email into email field", "tool": "browser_type", "args": {"selector": "#email", "text": "user@example.com"}},
       {"title": "Enter Password", "description": "Type password into password field", "tool": "browser_type", "args": {"selector": "#password", "text": "secret123"}},
       {"title": "Click Login Button", "description": "Click submit button", "tool": "browser_click", "args": {"selector": "button[type='submit']", "text": "Log In"}},
       {"title": "Verify Login", "description": "Inspect updated page state", "tool": "browser_inspect", "args": {}}
     ]
   - Email Example ("Write/compose/send an email to user@example.com"):
      * ALWAYS use `gmail_send_email` with high-quality subject and full message body!
      * DO NOT use `gmail_create_draft` unless user explicitly requested "save as draft in gmail". NEXUS previews the email in the UI and gets user permission before sending via `gmail_send_email`.
      * IF `gmail_send_email` or connector tool is active: USE `gmail_send_email` directly!
       [{"title": "Send Email via Gmail API", "description": "Send email via authenticated API", "tool": "gmail_send_email", "args": {"to": "user@example.com", "subject": "Update", "body": "All good"}}]
     * ONLY if NO email connector is connected, fall back to browser webmail:
       [
         {"title": "Open Webmail", "description": "Navigate to Gmail or webmail", "tool": "browser_navigate", "args": {"url": "https://mail.google.com"}},
         {"title": "Wait for Webmail", "description": "Allow webmail to load", "tool": "browser_wait", "args": {"timeout_seconds": 2.0}},
         {"title": "Click Compose", "description": "Click Compose button", "tool": "browser_click", "args": {"selector": "div[role='button'][gh='cm'], [aria-label*='Compose' i]", "text": "Compose"}},
         {"title": "Enter Recipient", "description": "Type recipient email address", "tool": "browser_type", "args": {"selector": "input[aria-label*='To recipients' i], input[name='to'], div[aria-label*='To' i] input", "text": "user@example.com", "press_enter": true}},
         {"title": "Enter Subject", "description": "Type email subject", "tool": "browser_type", "args": {"selector": "input[name='subjectbox'], input[aria-label*='Subject' i]", "text": "Update"}},
         {"title": "Enter Email Body", "description": "Type message content into rich body field", "tool": "browser_type", "args": {"selector": "div[role='textbox'][aria-label*='Message Body' i], div[contenteditable='true'][aria-label*='Body' i]", "text": "All good"}},
         {"title": "Send Email", "description": "Click Send button", "tool": "browser_click", "args": {"selector": "div[role='button'][data-tooltip*='Send' i], div[role='button'][aria-label*='Send' i]", "text": "Send"}}
       ]

3. TIER 2 (SECONDARY): Desktop GUI & VLM Hardware Automation (OS Desktop Windows & Canvas Only)
   - Use ONLY when interacting with non-web desktop windows (e.g. Paint, Calculator, desktop apps) or canvas-based web elements where DOM is unavailable.
   - Hardware control tools: `inspect_screen`, `dismiss_overlay`, `click_mouse`, `type_text`, `press_key`, `press_hotkey`, `activate_window`.

4. CRITICAL EXECUTION MANDATES:
   - For all web pages and websites, PREFER `browser_navigate`, `browser_inspect`, `browser_click`, `browser_type`, `browser_select` over `inspect_screen` / `click_mouse`!
   - NEVER output tutorial steps, bash scripts, batch scripts, or instructions telling the user how to do the task themselves!
   - NEVER claim "I cannot access your computer" or "I cannot save files to your desktop". NEXUS is an autonomous execution agent running directly on the host OS with full file creation and system execution capabilities!
   - If the user asks to create, make, write, save, open, delete, or run anything on their computer, YOU MUST DIRECTLY EXECUTE IT.
   - "ai_response" is STRICTLY FORBIDDEN for any request asking to perform real actions (except interactive scope clarifications).

Available tools:
Structured Browser Tools (CDP & Live DOM):
- "browser_navigate": args: {"url": "<url>", "new_tab": false}
- "browser_inspect": args: {"include_html": false, "max_elements": 60}
- "browser_click": args: {"selector": "<css_selector>", "text": "<optional_button_text>", "xpath": "<optional_xpath>"}
- "browser_type": args: {"selector": "<css_selector>", "text": "<text_to_type>", "clear_first": true, "press_enter": true}
- "browser_select": args: {"selector": "<css_selector>", "value": "<opt_val>", "label": "<opt_label>", "index": -1}
- "browser_press": args: {"key": "Enter|Escape|Tab|ArrowDown", "selector": "<optional_css_selector>"}
- "browser_wait": args: {"selector": "<optional_selector>", "text": "<optional_text>", "url_contains": "<opt_url>", "timeout_seconds": 5.0}
- "browser_get_tabs": args: {}
- "browser_switch_tab": args: {"tab_id": "<tab_id_or_url_or_title>"}
- "browser_get_source": args: {"selector": "<optional_css_selector>", "max_chars": 60000}
- "browser_execute_js": args: {"script": "<javascript_code>"}
- "browser_scroll": args: {"selector": "<optional_css_selector>", "x": 0, "y": 0}

Guidelines for Web Requests:
- For simple website opening or navigation requests (e.g. "open youtube", "open https://example.com", "go to reddit"), output ONLY a single "browser_navigate" step. Do NOT attach "browser_inspect" or multi-step inspection loops unless the user explicitly requested searching, interacting, or extracting data.
- For search queries on search engines or video/content platforms (e.g. "search coldplay on youtube", "search quantum computing on google", "search reddit for mechanical keyboards"), navigate DIRECTLY to the platform's search results URL with the encoded query! (e.g. "https://www.youtube.com/results?search_query=coldplay" or "https://www.google.com/search?q=quantum+computing"). Do NOT do slow multi-step homepage loading and typing when a direct search URL exists!
- When typing into search boxes, query inputs, or chat composers using `browser_type`, ALWAYS set "press_enter": true so the search or message is immediately submitted! Never leave text unsubmitted in a search box.
- For interactive tasks (forms, multi-step navigation, clicks), chain `browser_navigate` -> `browser_inspect` -> `browser_click`/`browser_type`.
- For Google Forms or form automation: NEVER stop at simply navigating to the forms page or dismissing preview dialogs! A form creation task requires actively setting the form title and adding each requested question/field. If the user did not specify fields, start with `ask_user` to prompt for desired fields/presets, then build the form with those fields.
- Tab Preservation: Never close any tabs unnecessarily or replace URLs of existing user tabs. If a web service is already open, prefer switching to it (`browser_switch_tab`).

DOCX Document Automation Tools:
- "document_create": args: {"path": "<optional_output_file_path>"}
- "document_open": args: {"path": "<file_path>"}
- "document_add_title": args: {"text": "<title_text>"}
- "document_add_heading": args: {"text": "<heading_text>", "level": 1}
- "document_add_paragraph": args: {"text": "<paragraph_text>"}
- "document_add_bullet": args: {"text": "<bullet_text>"}
- "document_add_numbered_item": args: {"text": "<numbered_item_text>"}
- "document_add_table": args: {"headers": ["<col1>", "<col2>"], "rows": [["<r1c1>", "<r1c2>"]]}
- "document_add_page_break": args: {}
- "document_add_image": args: {"path": "<image_path>", "width_inches": 6.0}
- "document_save": args: {"path": "<output_docx_path>"} (e.g. "Desktop/filename.docx")
- "document_read": args: {"path": "<file_path>"}
- "word_format_active": args: {"font_size": 20.0, "font_name": "Arial", "bold": true, "italic": true, "underline": false, "color": "blue", "alignment": "left|center|right|justify", "style": "Normal", "text": "<text>"}
- "excel_format_active": args: {"range_address": "B5", "value": 100, "formula": "=SUM(B2:B9)", "bold": true, "font_size": 14.0, "font_name": "Calibri", "number_format": "currency", "column_width": 15.0}
* ACTIVE TARGET FORMATTING: When user targets Microsoft Word or Microsoft Excel and gives formatting or value commands ("Make this 20pt", "Make this blue", "Change B5 to 100", "Format as currency"), use `word_format_active` or `excel_format_active` directly!

Deep Web Research & Multi-Format Document Compilation Tools:
- "deep_research": args: {"topic": "<detailed research prompt>", "output_format": "docx|pdf|xlsx|csv|md|html|txt|json|both", "output_path": "<optional output path, e.g. Desktop/Report.xlsx>", "requested_format": "<optional proprietary format if user requested cpr, psd, etc.>", "depth": "deep"}
* MANDATORY DEEP RESEARCH RULE: Whenever the user asks to "do research", "deep research", "study", "investigate", "compile report with citations", or "research X and make a word/pdf/excel/csv/markdown/etc. file", YOU MUST ALWAYS USE `deep_research`!
* DYNAMIC FORMAT GENERATION: `deep_research` supports ANY programmatically generatable document format: Word (.docx), PDF (.pdf), Excel (.xlsx), CSV (.csv), Markdown (.md), HTML (.html), Plain Text (.txt), or JSON (.json), based directly on user requirement.
* PROPRIETARY BINARY FORMAT TRANSPARENCY: Proprietary host-application files (like Cubase .cpr, Photoshop .psd/.ps, Pro Tools .ptx, FL Studio .flp, After Effects .aep, Premiere .prproj, AutoCAD .dwg, Blender .blend) cannot be synthesized natively without host software. For these requests, pass `requested_format="<ext>"` to `deep_research`, which informs the user clearly of this limitation while compiling their complete research into a universal format (e.g. DOCX, PDF, or Excel).
* NEVER create empty placeholder documents with generic text for research questions. `deep_research` autonomously executes multi-angle live web searches, scrapes real sources, synthesizes extensive sections with citations [1], [2], and builds professional reports in the user's requested format.

Excel / XLSX Spreadsheet Automation Tools:
- "spreadsheet_create": args: {"path": "<optional_path>", "initial_sheet": "Sheet1"}
- "spreadsheet_open": args: {"path": "<file_path>"}
- "spreadsheet_list_sheets": args: {}
- "spreadsheet_create_sheet": args: {"title": "<sheet_name>"}
- "spreadsheet_rename_sheet": args: {"old_title": "<old>", "new_title": "<new>"}
- "spreadsheet_read_cell": args: {"cell": "A1", "sheet": "<optional>"}
- "spreadsheet_read_range": args: {"range": "A1:C10", "sheet": "<optional>"}
- "spreadsheet_read_sheet": args: {"sheet": "<optional>", "max_rows": 100}
- "spreadsheet_write_cell": args: {"cell": "A1", "value": "<val>", "sheet": "<optional>"}
- "spreadsheet_write_range": args: {"start_cell": "A1", "values": [["h1", "h2"], [1, 2]], "sheet": "<optional>"}
- "spreadsheet_add_formula": args: {"cell": "B10", "formula": "=SUM(B2:B9)", "sheet": "<optional>"}
- "spreadsheet_format_range": args: {"range": "A1:B1", "bold": true, "fill_color": "1F4E78", "color": "FFFFFF", "number_format": "currency", "sheet": "<optional>"}
- "spreadsheet_create_table": args: {"range": "A1:C10", "name": "ExpenseTable", "sheet": "<optional>"}
- "spreadsheet_create_chart": args: {"chart_type": "bar|line|pie", "data_range": "B1:B10", "title": "Chart Title", "position": "E2", "categories_range": "A2:A10", "sheet": "<optional>"}
- "spreadsheet_save": args: {"path": "<output_xlsx_path>"} (e.g. "Desktop/expenses.xlsx")
- "spreadsheet_read": args: {"path": "<file_path>"}
- "spreadsheet_verify": args: {"path": "<xlsx_path>", "min_rows": 1, "require_table": false, "require_chart": false}
* FOR SPREADSHEET TASKS: Start directly with `spreadsheet_create` or `spreadsheet_open`, write headers & data with `spreadsheet_write_range`, add formulas, format headers, add table/chart, save with `spreadsheet_save` (path e.g. "Desktop/report.xlsx"), and verify with `spreadsheet_verify`. Do NOT add redundant shell commands to locate folders.

Live Microsoft Excel Copilot Tools (Active Open Workbook via Win32 COM):
- "excel_formula": args: {"operation": "sum|average|count|counta|sumif|averageif|countif|if|ifs", "target_column": "<col>", "target_cell": "<optional>", "condition_column": "<col>", "condition_value": "<val>", "true_value": "<val>", "false_value": "<val>", "header_name": "<name>", "formula_string": "<formula>"}
- "excel_lookup": args: {"lookup_type": "xlookup|vlookup", "lookup_value_col": "<col>", "lookup_array_col": "<col>", "return_array_col": "<col>", "dest_col": "<col>", "dest_header": "<header>", "source_sheet": "<sheet>", "source_range": "<range>"}
- "excel_sort_filter": args: {"operation": "sort|filter|clear_filter", "key_column": "<col>", "order": "descending|ascending", "filter_criteria": "<criteria>", "filter_column": "<col>"}
- "excel_pivot": args: {"row_fields": ["<col1>"], "column_fields": ["<col2>"], "value_fields": ["<val_col>"], "aggregation": "sum|count|average|max|min", "dest_sheet": "Pivot_Summary"}
- "excel_conditional_format": args: {"column": "<col>", "range_address": "<range>", "operator": "greater|less|equal|between|color_scale|top_percent|duplicates", "value1": <val>, "style": "green_fill|red_fill|yellow_fill"}
- "excel_data_cleanup": args: {"operation": "remove_duplicates|text_to_columns|flash_fill", "columns": ["<col>"], "delimiter": ",", "destination_col": "<col>"}
- "excel_inspect": args: {}
* LIVE EXCEL COPILOT RULE: When the user requests operations inside their open Excel spreadsheet ("Calculate total sales", "Add SUM", "Average sales", "Use XLOOKUP", "Sort table by...", "Filter by...", "Create pivot table...", "Highlight sales above...", "Remove duplicates", "Split name into first and last name", "Flash fill"), USE THESE LIVE EXCEL COPILOT TOOLS! They execute directly and instantaneously inside the user's open Excel window without generating a new file.

PowerPoint / PPTX Presentation Automation Tools:
- "presentation_create": args: {"topic": "<presentation topic>", "theme": "executive_navy|modern_dark|tech_indigo|emerald_green|corporate_light", "num_slides": 6}
- "presentation_save": args: {"path": "<optional_output_path>", "default_filename": "<filename.pptx>"}
- "presentation_read": args: {"path": "<file_path>"}
- "presentation_verify": args: {"path": "<pptx_path>", "min_slides": 1}
* FOR PRESENTATION TASKS: When the user asks to make, create, generate, or build a PowerPoint presentation, slide deck, or slides on a topic, start directly with `presentation_create`, prompt user for location with `ask_user` (options: Desktop, Documents, Downloads, Choose via File Explorer...), save with `presentation_save`, and verify with `presentation_verify`.


Desktop GUI & System Tools:


- "dismiss_overlay": args: {}
- "run_command": args: {"command": "<shell command>"}
- "write_file": args: {"path": "<path>", "content": "<content>"}
- "read_file": args: {"path": "<path>"}
- "delete_file": args: {"path": "<path>"}
- "list_directory": args: {"path": "<path>"}
- "search_files": args: {"query": "<query>", "path": "<optional path>"}
- "inspect_screen": args: {"target": "<optional element to find>"}
- "click_mouse": args: {"target": "<name of button to click>"} or {"x": <int>, "y": <int>}
- "type_text": args: {"text": "<text>", "target": "<optional input box>"}
- "press_key": args: {"key": "<key>"}
- "press_hotkey": args: {"keys": ["<key1>", "<key2>", ...]}
- "activate_window": args: {"title": "<window title substring>"}
- "web_search": args: {"query": "<search keywords>"}
- "get_current_time": args: {}
- "media_control": args: {"action": "play|pause|next|previous|stop|volume_up|volume_down|mute"}
- "play_music": args: {"query": "<song/artist/genre>", "service": "spotify|youtube", "prefer_desktop": true}
- "ai_response": args: {"answer": "<direct answer for informational questions>"}


Output strictly a JSON array of step objects:
[
  {
    "title": "Short action title",
    "description": "What this step accomplishes",
    "tool": "tool_name",
    "args": { ... }
  }
]
"""

NEXUS_CAPABILITIES_RESPONSE = """Hello! I am **NEXUS** — an autonomous AI execution and interaction runtime.

### Capabilities:
- **Autonomous Planning**: Deconstruct complex goals into discrete, verifiable execution steps.
- **Live Web & Google Search**: Real-time web retrieval for news, facts, documentation, and live data.
- **System Date & Time**: Real-time awareness of current local and UTC dates, times, and timezones.
- **Ultra-Fast Groq Reasoning**: Powered by Groq Compound models on Groq LPUs.
- **Filesystem Operations**: Read, create, edit, search, and manage project files.
- **Shell & Terminal Automation**: Execute commands, inspect processes, and run builds.
- **Risk-Aware Permission Gate**: Destructive or high-risk operations require your explicit approval before running.
- **Local Persistent Store**: Settings and credentials stay secure on your machine (~/.nexus/settings.json).

---
To enable live AI generation & reasoning:
Click the Settings icon in the top-right corner of the Spotlight bar to add your Groq API Key (gsk_...)."""


def _get_fallback_answer(goal: str) -> str:
    clean_goal = goal.strip()
    lower = clean_goal.lower()

    greeting_patterns = [
        r"^(?:hello|hi|hey|greetings|howdy)(?:\s+there|\s+nexus|\s+assistant|\s*!|\s*\.|\s*)?$",
        r"^(?:who|what)\s+are\s+you\??$",
        r"^(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|help(?:\s+me)?)\??$",
        r"^(?:about\s+nexus|what\s+is\s+nexus)\??$",
    ]
    if any(re.match(p, lower) for p in greeting_patterns):
        return NEXUS_CAPABILITIES_RESPONSE

    has_key = bool(get_groq_api_key() or get_gemma_api_key())
    if not has_key:
        return (
            f"[Groq API Key Not Configured]\n\n"
            f"To process '{clean_goal}' and execute intelligent agent tasks, NEXUS needs access to Groq LPUs.\n\n"
            f"Click the Settings icon in the top-right of the Spotlight bar to add your Groq API Key (gsk_...)."
        )

    return f"I could not formulate an automated plan for '{clean_goal}'. Please try rephrasing your request."


def _clean_and_parse_json(content: str) -> list[dict]:
    """Robust JSON extraction allowing control characters, markdown, and dict wrappers."""
    if not content:
        return []
    content = content.strip()

    # 1. Direct parse
    try:
        data = json.loads(content, strict=False)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("steps", "plan", "tasks", "items"):
                if isinstance(data.get(k), list):
                    return data[k]
    except Exception:
        pass

    import re

    # 2. Markdown code block
    match = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1), strict=False)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for k in ("steps", "plan", "tasks", "items"):
                    if isinstance(data.get(k), list):
                        return data[k]
        except Exception:
            pass

    # 3. Slice between outermost brackets
    if "[" in content and "]" in content:
        start = content.index("[")
        end = content.rindex("]") + 1
        raw = content[start:end]
        try:
            data = json.loads(raw, strict=False)
            if isinstance(data, list):
                return data
        except Exception:
            pass

        # Trailing comma fix
        try:
            cleaned = re.sub(r",\s*([\]}])", r"\1", raw)
            data = json.loads(cleaned, strict=False)
            if isinstance(data, list):
                return data
        except Exception:
            pass

        # Control characters inside raw string fix
        try:
            sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: '\\n' if m.group(0) == '\n' else '\\t' if m.group(0) == '\t' else '', raw)
            data = json.loads(sanitized, strict=False)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return []


async def _stream_llm_to_string(llm, messages, on_token=None) -> str:
    """Stream LLM tokens, call on_token(chunk) for each, and return the full accumulated string."""
    import asyncio
    content = ""
    async for chunk in llm.astream(messages):
        piece = chunk.content if hasattr(chunk, "content") else str(chunk)
        if piece:
            content += piece
            if on_token:
                try:
                    if asyncio.iscoroutinefunction(on_token):
                        await on_token(piece)
                    else:
                        on_token(piece)
                except Exception:
                    pass
    return content


def _detect_research_format(goal: str) -> tuple[str, Optional[str], str]:
    """
    Detect desired document/data format from user goal.
    Supports: docx, pdf, xlsx, csv, md, html, txt, json, multi-formats (e.g. 'docx,pdf'),
    and detects unsupported proprietary formats (.cpr, .psd, etc.) to set requested_format.

    Returns: (output_format, requested_format, primary_extension)
    """
    import re
    lower = goal.lower()

    # 1. Check for proprietary/unsupported formats
    unsupported_patterns = {
        "cpr": (r"\b(cpr|cubase)\b", "docx"),
        "psd": (r"\b(psd|photoshop)\b", "pdf"),
        "ps": (r"\b(\.ps|postscript)\b", "pdf"),
        "ptx": (r"\b(ptx|pro\s*tools)\b", "docx"),
        "flp": (r"\b(flp|fl\s*studio)\b", "docx"),
        "aep": (r"\b(aep|after\s*effects)\b", "pdf"),
        "prproj": (r"\b(prproj|premiere)\b", "pdf"),
        "dwg": (r"\b(dwg|autocad)\b", "pdf"),
        "blend": (r"\b(blend|blender)\b", "pdf"),
        "max": (r"\b(max|3ds\s*max)\b", "docx"),
        "exe": (r"\bexe\b", "txt"),
    }

    for ext, (pat, fallback_fmt) in unsupported_patterns.items():
        if re.search(pat, lower):
            # If user also mentioned excel/csv/table, use xlsx fallback
            if any(w in lower for w in ("excel", "xlsx", "spreadsheet", "sheet", "csv", "table", "data", "matrix")):
                fallback_fmt = "xlsx"
            elif "pdf" in lower:
                fallback_fmt = "pdf"
            elif any(w in lower for w in ("word", "docx", "doc")):
                fallback_fmt = "docx"
            return (fallback_fmt, ext, fallback_fmt)

    # 2. Check for multi-format requests
    wants_word = bool(re.search(r"\b(word|docx|doc)\b", lower))
    wants_pdf = bool(re.search(r"\bpdf\b", lower))
    wants_excel = bool(re.search(r"\b(excel|xlsx|spreadsheet|sheet)\b", lower))
    wants_csv = bool(re.search(r"\bcsv\b", lower))
    wants_md = bool(re.search(r"\b(markdown|md)\b", lower))
    wants_html = bool(re.search(r"\b(html|webpage)\b", lower))
    wants_txt = bool(re.search(r"\b(plain\s*text|txt|text\s*file)\b", lower))
    wants_json = bool(re.search(r"\bjson\b", lower))

    if ("both" in lower or "word and pdf" in lower or "pdf and word" in lower or "docx and pdf" in lower) and not (wants_excel or wants_csv):
        return ("docx,pdf", None, "docx")

    selected_formats = []
    if wants_word:
        selected_formats.append("docx")
    if wants_pdf:
        selected_formats.append("pdf")
    if wants_excel:
        selected_formats.append("xlsx")
    if wants_csv:
        selected_formats.append("csv")
    if wants_md:
        selected_formats.append("md")
    if wants_html:
        selected_formats.append("html")
    if wants_txt:
        selected_formats.append("txt")
    if wants_json:
        selected_formats.append("json")

    if len(selected_formats) > 1:
        return (",".join(selected_formats), None, selected_formats[0])
    elif len(selected_formats) == 1:
        fmt = selected_formats[0]
        return (fmt, None, fmt)

    # Default to docx
    return ("docx", None, "docx")


def _extract_clean_research_topic(goal: str) -> str:
    """Extract clean research topic from user prompt by stripping research action phrases."""
    import re
    topic = goal.strip()
    # Strip explicit focus/subtopic clauses first
    topic = re.sub(
        r"[\s,;]+(?:focus(?:ing)?\s+on|subtopics?|priority|prioritize|with\s+focus\s+on|format|output).*$",
        "",
        topic,
        flags=re.IGNORECASE
    )
    # Strip leading action directives
    topic = re.sub(
        r"^(?:please\s+)?(?:do|conduct|perform|run|execute|make|create|generate|write|compile|get|fetch|find)?\s*"
        r"(?:a\s+|an\s+|the\s+|some\s+)?(?:comprehensive\s+|in-depth\s+|detailed\s+|thorough\s+|exhaustive\s+|market\s+|industry\s+|academic\s+)?"
        r"(?:deep\s+)?(?:research|study|investigation|analysis|report|overview|paper|breakdown)"
        r"(?:\s+(?:on|about|regarding|into|for|of))?\s*",
        "",
        topic,
        flags=re.IGNORECASE
    )
    # Strip trailing output/format directives
    topic = re.sub(
        r"\s*(?:and\s+)?(?:compile|export|save|write|put)?\s*"
        r"(?:into|in|as|to)?\s*(?:a\s+|an\s+|the\s+)?(?:word|doc|docx|pdf|excel|xlsx|spreadsheet|sheet|csv|markdown|md|html|text|txt|json|report|file|document)?\s*"
        r"(?:format|file|document)?\s*(?:on\s+desktop|to\s+desktop)?$",
        "",
        topic,
        flags=re.IGNORECASE
    )
    topic = re.sub(r"^(?:the|a|an)\s+", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\s+", " ", topic).strip()
    return topic if topic else goal.strip()


def _is_research_reply(goal: str) -> bool:
    """Check if the user prompt is a reply to a deep research clarification question."""
    import re
    lower = goal.lower().strip()
    if re.fullmatch(r"^(?:option|choice|number|#)?\s*\d+(?:\s*[,&and]\s*(?:option|choice|number|#)?\s*\d+)*$", lower):
        return True

    reply_keywords = (
        "cover all", "all of the above", "all of them", "all subtopics", "everything",
        "option 1", "option 2", "option 3", "option 4", "option 5", "option 6",
        "choice 1", "choice 2", "choice 3",
        "standard overview", "standard research", "deep research", "exhaustive deep-dive", "exhaustive",
        "save on desktop", "save to desktop", "in docx", "in word"
    )
    return any(k in lower for k in reply_keywords)


def _has_explicit_research_params(goal: str) -> bool:
    """Check whether prompt already contains explicit subtopic focus or depth level choices or is a reply to clarification."""
    lower = goal.lower().strip()
    if _is_research_reply(goal):
        return True

    explicit_indicators = (
        "focus on", "focusing on", "subtopic", "subtopics", "depth:", "depth level",
        "proceed", "confirm", "start research", "go ahead", "all subtopics", "all of the above", "cover all",
        "1,", "2,", "3,", "4,", "option 1", "option 2", "option 3", "focal area", "focal areas",
        "exhaustive", "deep research,", "standard research,", "save on desktop", "save to desktop",
        "in docx", "as docx", "in word", "as word"
    )
    return any(ind in lower for ind in explicit_indicators)


def _find_recent_research_topic(goal: str, state_messages: Optional[list] = None) -> str:
    """Extract topic from current prompt, or look back in conversation history if prompt is a short reply."""
    import re
    topic_from_goal = _extract_clean_research_topic(goal)
    lower_topic = topic_from_goal.lower().strip()
    is_generic = (
        re.fullmatch(r"^(?:option|choice|number|#)?\s*\d+(?:\s*[,&and]\s*(?:option|choice|number|#)?\s*\d+)*$", lower_topic) or
        lower_topic in ("1", "2", "3", "4", "5", "6", "all", "all of the above", "cover all", "everything", "yes", "go ahead", "do it", "deep research", "standard", "exhaustive", "docx", "word")
    )
    if not is_generic and len(topic_from_goal) > 2:
        return topic_from_goal

    if state_messages:
        for msg in reversed(state_messages):
            content = ""
            if isinstance(msg, dict):
                content = msg.get("content") or ""
            elif hasattr(msg, "content"):
                content = getattr(msg, "content", "") or ""

            match_bold = re.search(r"research\s+(?:on|about|regarding)\s+\*\*([^*]+)\*\*", content, re.IGNORECASE)
            if match_bold:
                return match_bold.group(1).strip()

            match_title = re.search(r"Research Scope & Focus Options \(([^)]+)\)", content, re.IGNORECASE)
            if match_title:
                return match_title.group(1).strip()

            match_human = re.search(r"(?:research|study|investigate)\s+(?:on|about|regarding|into)?\s*([a-zA-Z0-9\s]{3,50})", content, re.IGNORECASE)
            if match_human:
                extracted = _extract_clean_research_topic(match_human.group(0))
                if len(extracted) > 2:
                    return extracted

    return "Research_Report"


def _extract_subtopics_from_prompt(goal: str) -> list[str]:
    """Extract explicit subtopic list if provided in prompt."""
    import re
    focus_match = re.search(
        r"(?:focus(?:ing)?\s+on|subtopics?|prioritize|priority|focus)\s*[:=]?\s*([^,\n;]+(?:\s*,\s*[^,\n;]+)*)",
        goal,
        re.IGNORECASE
    )
    if focus_match:
        raw_focus = focus_match.group(1).strip()
        parts = re.split(r",|\band\b", raw_focus)
        subtopics = [
            p.strip() for p in parts
            if p.strip() and p.strip().lower() not in ("format", "pdf", "docx", "excel", "xlsx", "word", "markdown")
        ]
        if subtopics:
            return subtopics
    return []


async def _generate_subtopic_suggestions(topic: str) -> list[tuple[str, str]]:
    """Generate 4-5 relevant subtopic focus options for a given research topic."""
    import asyncio
    import re
    from backend.agent.router.model_router import ainvoke_with_dynamic_switch, get_groq_api_key
    from langchain_core.messages import SystemMessage, HumanMessage

    if get_groq_api_key():
        try:
            prompt = (
                "You are a Senior Strategic Research Planner. Given a research topic, generate 4 to 5 distinct, "
                "high-value subtopics or focal areas for a comprehensive research report.\n"
                "Output strictly a JSON array of objects with keys 'title' and 'description'.\n"
                "Example: [{\"title\": \"Subtopic Name\", \"description\": \"Brief 1-line focus description\"}]"
            )
            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [SystemMessage(content=prompt), HumanMessage(content=f"Topic: {topic}")],
                    operation="fast",
                    temperature=0.2,
                ),
                timeout=3.5,
            )
            match = re.search(r"\[.*?\]", res.content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list) and len(parsed) >= 2:
                    return [(str(item.get("title")), str(item.get("description"))) for item in parsed[:5] if item.get("title")]
        except Exception:
            pass

    # Domain Fallbacks
    lower = topic.lower()
    if any(k in lower for k in ("space", "satellite", "isro", "launch", "aerospace", "orbit", "skyroot", "agnikul", "in-space")):
        return [
            ("IN-SPACe & Regulatory Framework", "Space Policy 2023, FDI liberalizations, and ISRO tech transfer."),
            ("Launch Vehicle Startups & Infrastructure", "Skyroot Aerospace (Vikram), Agnikul Cosmos (Agnibaan), and private launchpads."),
            ("Satellite Manufacturing & Earth Observation", "Pixxel hyperspectral constellations, Dhruva Space, and GalaxEye."),
            ("Investment & Financial Landscape", "Capital inflow, valuation growth, and venture funding trends."),
            ("Commercial & Defense Applications", "SatCom integration, defense contracts, and global export potential."),
        ]
    elif any(k in lower for k in ("ai", "artificial intelligence", "machine learning", "llm", "neural")):
        return [
            ("Core Architectural Innovations", "Foundation model breakthroughs, training efficiency, and benchmarks."),
            ("Infrastructure & Compute Economics", "GPU availability, cloud infrastructure, and inference optimization."),
            ("Industry Applications & Enterprise Adoption", "Real-world deployment across healthcare, finance, and automation."),
            ("Regulatory & Governance Policies", "AI safety regulations, copyright issues, and compliance frameworks."),
            ("Market Trends & Future Trajectory", "Funding landscapes, open-source vs proprietary models, and outlook."),
        ]
    else:
        return [
            ("Market Overview & Historical Evolution", "Foundational milestones, structural shifts, and market size."),
            ("Key Players, Startups & Industry Leaders", "Dominant entities, emerging disruptors, and strategic positioning."),
            ("Regulatory Framework & Government Policy", "Relevant legislation, standards, and institutional support."),
            ("Financial Performance & Investment Trends", "Funding channels, revenue drivers, and economic impact."),
            ("Future Outlook & Strategic Challenges", "Emerging innovations, growth bottlenecks, and multi-year trajectory."),
        ]


async def _build_deep_research_clarification_response(topic: str, goal: str) -> str:
    import re
    clean_topic = _extract_clean_research_topic(goal)
    formatted_topic = clean_topic.strip().title()
    subtopic_pairs = await _generate_subtopic_suggestions(clean_topic)

    subtopics_text = "\n".join([f"   {i}. **{title}**: {desc}" for i, (title, desc) in enumerate(subtopic_pairs, 1)])
    filename = re.sub(r"[^\w\s-]", "", clean_topic)
    filename = "_".join(filename.split()[:7]) or "Research_Report"

    return f"""I'd be glad to help you conduct deep research on **{formatted_topic}** and compile a detailed Word document (`Desktop/{filename}.docx`) for you!

To make sure I capture exactly what you need, could you share a few details?

1. **Depth Level**: How deep should I go? (Standard overview, Deep research, or Exhaustive deep-dive?)
2. **Focal Subtopics**: Which key areas should we focus on?
{subtopics_text}
   {len(subtopic_pairs) + 1}. **Cover All of the Above**

3. **Save Location**: I'll save it as a Word document at `Desktop/{filename}.docx` by default. Let me know if you'd prefer a custom location or filename!

Feel free to reply with your choices or any specific angles you'd like me to cover!"""



def _build_google_forms_plan(goal: str) -> list[dict]:
    """Build interactive Google Form creation plan with field prompting via ask_user."""
    import re
    lower = goal.lower().strip()

    # Check if user specified fields in their prompt
    fields_match = re.search(r"(?:with|containing|having|fields?|questions?)\s+(.+)", goal, re.IGNORECASE)
    specified_fields = []
    if fields_match:
        raw_fields = fields_match.group(1).strip()
        raw_fields = re.split(r"\b(?:and\s+save|then|please)\b", raw_fields, flags=re.IGNORECASE)[0]
        tokens = [f.strip(" ,.;:'\"") for f in re.split(r"[,;]\s*|\band\b", raw_fields) if f.strip(" ,.;:'\"")]
        specified_fields = [
            t for t in tokens
            if len(t) >= 2 and not any(skip == t.lower() for skip in ("google", "form", "forms", "a", "the", "new", "fields", "questions"))
        ]

    # Inferred or extracted form title
    title_match = re.search(r"(?:titled|named|called|for)\s+['\"]([^'\"]+)['\"]", goal, re.IGNORECASE)
    if title_match:
        form_title = title_match.group(1).strip()
    elif "contact" in lower:
        form_title = "Contact Form"
    elif "registration" in lower or "register" in lower:
        form_title = "Registration Form"
    elif "feedback" in lower or "survey" in lower:
        form_title = "Feedback Survey"
    else:
        form_title = "Automation Form"

    steps = []

    # If the user did not specify fields in their prompt, ask them via ask_user!
    if not specified_fields:
        steps.append({
            "title": "Ask User for Form Fields",
            "description": "Ask user what fields or questions to include in the Google Form",
            "tool": "ask_user",
            "args": {
                "prompt": "What fields or questions would you like to add to this Google Form?",
                "options": [
                    "Contact Form (Name, Email, Phone Number, Message)",
                    "Event Registration (Name, Email, RSVP, Dietary Requirements)",
                    "Feedback Survey (Rating, Experience Feedback, Suggestions)",
                    "Job Application (Name, Email, Resume Link, Experience)",
                ],
                "parameter_name": "form_fields",
                "placeholder": "e.g. Name, Email, Department, Joining Date",
            },
            "risk_level": "safe",
        })
        fields_to_create = ["{{question_1}}", "{{question_2}}", "{{question_3}}", "{{question_4}}"]
        active_title = "{{form_title}}"
    else:
        fields_to_create = specified_fields
        active_title = form_title

    # 1. Open Google Forms
    steps.append({
        "title": "Open Google Forms",
        "description": "Open Google Forms editor in browser",
        "tool": "browser_navigate",
        "args": {"url": "https://forms.new"},
    })

    # 2. Dismiss onboarding / Gemini preview dialog
    steps.append({
        "title": "Dismiss Popups & Gemini Dialog",
        "description": "Dismiss onboarding dialogs and Help me write popup",
        "tool": "browser_dismiss_popup",
        "args": {},
    })

    # 3. Wait for Form to render
    steps.append({
        "title": "Wait for Form Load",
        "description": "Allow form editor DOM to stabilize",
        "tool": "browser_wait",
        "args": {"timeout_seconds": 2.0},
    })

    # 4. Set Form Title
    steps.append({
        "title": f"Set Form Title: {active_title}",
        "description": "Enter form title",
        "tool": "browser_type",
        "args": {
            "selector": "input[aria-label*='Form title' i], [role='heading'][contenteditable='true']",
            "text": active_title,
            "clear_first": True,
        },
    })

    # 5. Populate first question
    first_field = fields_to_create[0] if fields_to_create else "Name"
    steps.append({
        "title": f"Set Question 1: {first_field}",
        "description": "Set Question 1 title",
        "tool": "browser_type",
        "args": {
            "selector": "div[role='listitem'] [contenteditable='true'], [aria-label*='Question title'], [role='heading'][contenteditable='true']",
            "text": first_field,
            "clear_first": True,
        },
    })

    # 6. Add subsequent questions with the '+' button
    for idx, field in enumerate(fields_to_create[1:], start=2):
        steps.append({
            "title": f"Add Question {idx}",
            "description": "Click Add question button",
            "tool": "browser_click",
            "args": {
                "selector": "[aria-label*='Add question'], div[data-tooltip*='Add question'], div[role='button'][aria-label*='question']",
                "text": "Add question",
            },
        })
        steps.append({
            "title": f"Type Question {idx}: {field}",
            "description": f"Set Question {idx} title",
            "tool": "browser_type",
            "args": {
                "selector": "div[role='listitem']:last-of-type [contenteditable='true'], div[aria-selected='true'] [contenteditable='true'], [aria-label*='Question title']",
                "text": field,
                "clear_first": True,
            },
        })

    return steps


async def _try_fast_path_plan(
    goal: str,
    intent: str,
    active_target: Optional[dict] = None,
    active_context: Optional[dict] = None,
    state_messages: Optional[list] = None,
    user_name: Optional[str] = None,
) -> list[dict]:
    """
    Zero-latency deterministic compiler for standard commands.
    Returns structured plan steps in <1ms without requiring an LLM roundtrip.
    """
    import re
    lower = goal.lower().strip()

    # 0. Deep Research & Multi-Source Document Compilation Fast-Path
    is_reply = _is_research_reply(goal)
    is_deep_research = is_reply or (
        any(k in lower for k in (
            "deep research", "do research", "research on", "research about", "do some research", "some research on",
            "study on", "study about", "investigate", "market research",
            "industry research", "comprehensive research", "surf web",
            "in-depth research", "compile research", "detailed research", "look into", "find information on"
        )) or (
            any(k in lower for k in ("research", "study", "analysis", "investigate")) and
            any(w in lower for w in (
                "document", "word", "docx", "doc", "pdf", "report", "file", "make", "create", "write",
                "excel", "xlsx", "spreadsheet", "sheet", "csv", "markdown", "md", "html", "text", "txt", "json",
                "cpr", "psd", "ps", "flp", "ptx", "aep", "blend", "dwg"
            ))
        )
    )

    if is_deep_research:
        clean_topic = _find_recent_research_topic(goal, state_messages)
        fmt, req_fmt, primary_ext = _detect_research_format(goal)

        # Check if user prompt is missing explicit depth or focal subtopic choices
        if not _has_explicit_research_params(goal):
            clarification_msg = await _build_deep_research_clarification_response(clean_topic, goal)
            return [
                {
                    "title": f"Research Scope & Focus Options ({clean_topic.title()})",
                    "description": f"Prompt user for depth level and focal subtopics for research on '{clean_topic}'",
                    "tool": "ai_response",
                    "args": {
                        "answer": clarification_msg
                    }
                }
            ]

        # Explicit research params or reply present — resolve subtopics & execute research
        subtopics = _extract_subtopics_from_prompt(goal)

        # Parse numeric selections like "1", "2", "1, 2", "all" from user reply
        suggestions = await _generate_subtopic_suggestions(clean_topic)
        digits = [int(d) for d in re.findall(r"\b[1-6]\b", goal)]
        if "all" in lower or "cover all" in lower or "everything" in lower or 6 in digits or (len(suggestions) + 1) in digits:
            subtopics = [title for title, desc in suggestions]
        elif digits and not subtopics:
            matched = []
            for d in digits:
                if 1 <= d <= len(suggestions):
                    matched.append(suggestions[d - 1][0])
            if matched:
                subtopics = matched

        filename = re.sub(r"[^\w\s-]", "", clean_topic)
        filename = "_".join(filename.split()[:7]) or "Research_Report"
        target_path = f"Desktop/{filename}.{primary_ext}"

        depth_val = "exhaustive" if "exhaustive" in lower else "deep"

        args = {
            "topic": clean_topic,
            "output_format": fmt,
            "output_path": target_path,
            "depth": depth_val,
        }
        if subtopics:
            args["subtopics"] = subtopics
        if req_fmt:
            args["requested_format"] = req_fmt

        desc = (
            f"Autonomous deep web research on '{clean_topic}' compiled into {fmt.upper()} (note: proprietary .{req_fmt} cannot be generated)"
            if req_fmt
            else f"Gather live sources and conduct in-depth multi-source research on '{clean_topic}' into {fmt.upper()}"
        )

        return [
            {
                "title": f"Autonomous Deep Web Research ({clean_topic.title()})",
                "description": desc,
                "tool": "deep_research",
                "args": args,
            }
        ]

    # Active Target Fast-Paths (Word & Excel)
    target_app = (active_target.get("application") if active_target else "").lower()
    target_type = (active_target.get("target_type") if active_target else "").lower()

    is_word_target = target_type == "word" or ("word" in target_app and target_type != "auto")
    is_explicit_word_prompt = any(k in lower for k in ("in word", "word document", "word file", "page border", "headings in word"))

    if is_word_target or is_explicit_word_prompt:
        font_size = None
        color = None
        bold = None
        italic = None
        align = None
        font_name = None
        page_border = None
        header = None
        footer = None
        page_number = None
        target_scope = "selection"

        if any(k in lower for k in ("all headings", "all heading", "headings", "every heading", "the headings", "heading font")):
            target_scope = "headings"
        elif any(k in lower for k in ("all text", "entire document", "whole document", "all paragraphs", "every paragraph", "everything", "page border", "border")):
            target_scope = "document"

        if "border" in lower or "page border" in lower:
            page_border = True

        if "header" in lower:
            h_match = re.search(r"header\s+[\"']?([a-zA-Z0-9_\s.-]+)[\"']?", lower)
            extracted_h = h_match.group(1).strip() if h_match else ""
            header = extracted_h if (extracted_h and extracted_h not in ("and", "footer", "page", "page number", "page numbers")) else "Header"

        if "footer" in lower:
            f_match = re.search(r"footer\s+[\"']?([a-zA-Z0-9_\s.-]+)[\"']?", lower)
            extracted_f = f_match.group(1).strip() if f_match else ""
            footer = extracted_f if (extracted_f and extracted_f not in ("and", "header", "page", "page number", "page numbers")) else "Footer"

        if any(k in lower for k in ("page number", "page numbers", "pagenumber", "page num")):
            page_number = True

        # Parse font size e.g. "10pt", "10 pt", "size 10", "10"
        size_match = re.search(r"\b(\d+)\s*(?:pt|point|px)?\b", lower)
        if size_match and any(k in lower for k in ("pt", "point", "size", "font", "headings", "heading")):
            font_size = float(size_match.group(1))

        # Parse colors
        for c in ("blue", "red", "green", "black", "yellow", "orange", "purple"):
            if c in lower:
                color = c
                break

        # Parse bold / italic / alignment
        if "bold" in lower:
            bold = True
        if "italic" in lower:
            italic = True
        if "center" in lower:
            align = "center"
        elif "right" in lower:
            align = "right"
        elif "left" in lower:
            align = "left"

        if any(f in lower for f in ("arial", "calibri", "times new roman", "courier", "verdana", "georgia")):
            for fn in ("Arial", "Calibri", "Times New Roman", "Courier", "Verdana", "Georgia"):
                if fn.lower() in lower:
                    font_name = fn
                    break

        if any(v is not None for v in (font_size, color, bold, italic, align, font_name, page_border, header, footer, page_number)) or target_scope != "selection":
            args = {"target_scope": target_scope}
            if page_border is not None: args["page_border"] = True
            if font_size is not None: args["font_size"] = font_size
            if color is not None: args["color"] = color
            if bold is not None: args["bold"] = bold
            if italic is not None: args["italic"] = italic
            if align is not None: args["alignment"] = align
            if font_name is not None: args["font_name"] = font_name
            if header is not None: args["header"] = header
            if footer is not None: args["footer"] = footer
            if page_number is not None: args["page_number"] = True

            return [{
                "title": f"Format Active Word Document ({target_scope})",
                "description": f"Apply formatting/header/footer to {target_scope} in Word: {args}",
                "tool": "word_format_active",
                "args": args,
            }]

    if target_type == "excel" or "excel" in target_app:
        cell_match = re.search(r"\b([a-zA-Z]{1,3}\d{1,5}(?::[a-zA-Z]{1,3}\d{1,5})?)\b", goal)
        range_addr = cell_match.group(1) if cell_match else None

        val_match = re.search(r"(?:to|=)\s*([0-9.]+)\b", lower)
        val = float(val_match.group(1)) if val_match else None
        if val is not None and val.is_integer():
            val = int(val)

        is_bold = True if "bold" in lower else None
        is_italic = True if "italic" in lower else None
        is_underline = True if "underline" in lower else None

        is_currency = True if any(k in lower for k in ("currency", "money", "$")) else None
        if "percent" in lower or "%" in lower:
            num_fmt = "0.0%"
        elif is_currency:
            num_fmt = "currency"
        else:
            num_fmt = None

        # Font size
        font_size = None
        size_match = re.search(r"\b(\d+)\s*(?:pt|point|px)?\b", lower)
        if size_match and any(k in lower for k in ("pt", "point", "size", "font", "cells", "cell")):
            font_size = float(size_match.group(1))

        # Font name
        font_name = None
        if any(f in lower for f in ("arial", "calibri", "times new roman", "courier", "verdana", "georgia")):
            for fn in ("Arial", "Calibri", "Times New Roman", "Courier", "Verdana", "Georgia"):
                if fn.lower() in lower:
                    font_name = fn
                    break

        # Alignments
        align = None
        if "center" in lower:
            align = "center"
        elif "right" in lower:
            align = "right"
        elif "left" in lower:
            align = "left"

        v_align = None
        if "top" in lower:
            v_align = "top"
        elif "bottom" in lower:
            v_align = "bottom"
        elif "middle" in lower or "vcenter" in lower:
            v_align = "center"

        # Colors & Fills
        color = None
        fill_color = None
        colors_list = ("blue", "red", "green", "black", "yellow", "orange", "purple", "white", "gray", "grey")
        for c in colors_list:
            if re.search(rf"\b(?:fill|background|highlight)\s+{c}\b|\b{c}\s+(?:fill|background)\b", lower):
                fill_color = c
            elif re.search(rf"\b(?:font|text|color)\s+{c}\b|\b{c}\s+(?:font|text)\b", lower):
                color = c

        if not color and not fill_color:
            for c in colors_list:
                if c in lower:
                    if "fill" in lower or "background" in lower:
                        fill_color = c
                    else:
                        color = c
                    break

        # Borders
        borders = True if any(k in lower for k in ("border", "borders", "outline")) else None

        # Wrap text
        wrap_text = True if "wrap" in lower else None

        # Sum / Total calculation requests on active Excel target
        is_sum_req = any(k in lower for k in ("sum", "total", "add sum", "make a sum", "calculate sum", "total of", "sum of"))
        if is_sum_req:
            col_match = re.search(r"column\s+([a-zA-Z]{1,2})\b|\b([a-zA-Z]{1,2})\s+column\b", lower)
            col_letter = (col_match.group(1) or col_match.group(2)).upper() if col_match else None
            
            target_range = range_addr or (f"{col_letter}" if col_letter else "goals")
            formula_arg = f"=SUM({col_letter}:{col_letter})" if col_letter else None

            args = {"range_address": target_range, "bold": True}
            if formula_arg:
                args["formula"] = formula_arg

            return [
                {
                    "title": "Insert Sum Total in Active Excel Workbook",
                    "description": f"Calculate and insert sum total in Excel for {target_range}: {args}",
                    "tool": "excel_format_active",
                    "args": args,
                },
                {
                    "title": "Save Active Excel Workbook",
                    "description": "Save changes in active Excel workbook via COM",
                    "tool": "spreadsheet_save",
                    "args": {},
                }
            ]

        if any(v is not None for v in (val, range_addr, is_bold, is_italic, is_underline, num_fmt, font_size, font_name, align, v_align, color, fill_color, borders, wrap_text)):
            args = {}
            if range_addr: args["range_address"] = range_addr
            if val is not None: args["value"] = val
            if is_bold: args["bold"] = True
            if is_italic: args["italic"] = True
            if is_underline: args["underline"] = True
            if num_fmt: args["number_format"] = num_fmt
            if font_size is not None: args["font_size"] = font_size
            if font_name: args["font_name"] = font_name
            if align: args["alignment"] = align
            if v_align: args["vertical_alignment"] = v_align
            if color: args["color"] = color
            if fill_color: args["fill_color"] = fill_color
            if borders: args["borders"] = borders
            if wrap_text: args["wrap_text"] = True

            return [{
                "title": "Update Active Excel Worksheet",
                "description": f"Format/update Excel range {range_addr or 'selection'}: {args}",
                "tool": "excel_format_active",
                "args": args,
            }]

    # 0. Media & Spotify Fast Path: e.g. "play music from spotify", "play starboy on spotify", "pause music", "next track", "volume up"
    try:
        from backend.agent.router.media_fastpath import build_media_plan
        media_plan = build_media_plan(goal)
        if media_plan:
            return media_plan
    except Exception:
        pass

    # 0.1 Search Fast Path: e.g. "search quantum computing on google", "search coldplay on youtube", "play bohemian rhapsody on youtube"
    try:
        from backend.agent.router.search_fastpath import build_search_plan
        search_plan = build_search_plan(goal)
        if search_plan:
            return search_plan
    except Exception:
        pass

    # 0.1 Recycle Bin Fast-Path: e.g. "empty my recycle bin", "clear recycle bin"
    if any(w in lower for w in ("recycle bin", "recyclebin", "trash bin")) and any(w in lower for w in ("empty", "clear", "clean", "purge", "delete", "dump")):
        return [
            {
                "title": "Empty Windows Recycle Bin",
                "description": "Permanently clear and remove all deleted files from the Windows Recycle Bin.",
                "tool": "run_command",
                "args": {
                    "command": "powershell.exe -NoProfile -Command \"Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Output 'Recycle Bin emptied successfully'\""
                },
                "risk_level": "DESTRUCTIVE"
            }
        ]

    # 0.2 Kill Process Fast-Path: e.g. "kill chrome", "close application", "terminate process"
    if any(w in lower for w in ("kill", "close", "terminate", "stop")) and any(w in lower for w in ("process", "app", "application", "chrome", "firefox", "notepad", "excel", "word")):
        process_name = ""
        for app in ("chrome", "firefox", "notepad", "excel", "word", "powershell", "cmd"):
            if app in lower:
                process_name = app
                break
        if not process_name:
            process_name = "chrome"
        return [
            {
                "title": f"Terminate {process_name.capitalize()} Process",
                "description": f"Force-kill all running {process_name} processes.",
                "tool": "run_command",
                "args": {
                    "command": f"taskkill /IM {process_name}.exe /F"
                },
                "risk_level": "PRIVILEGED"
            }
        ]

    # 0.3 Repeated text writing fast-path: e.g. "write I am dumb 10 times in a file"
    repeat_match = re.search(r"\bwrite\s+[\"']?(.+?)[\"']?\s+(\d+)\s+times\s+(?:in|into|to)\s+(?:a\s+)?(?:file|text file|txt|document)?(?:\s+(?:named|called)\s+[\"']?([a-zA-Z0-9_.-]+)[\"']?)?", goal, re.IGNORECASE)
    if repeat_match:
        text_to_repeat = repeat_match.group(1).strip()
        count = min(int(repeat_match.group(2)), 1000)
        raw_name = repeat_match.group(3) or "output.txt"
        file_name = raw_name if raw_name.endswith((".txt", ".md", ".log")) else f"{raw_name}.txt"
        target_path = f"Desktop/{file_name}" if "desktop" in lower else file_name
        repeated_content = "\n".join([text_to_repeat] * count) + "\n"
        return [
            {
                "title": f"Create {file_name}",
                "description": f"Write '{text_to_repeat}' {count} times into {file_name}",
                "tool": "write_file",
                "args": {
                    "path": target_path,
                    "content": repeated_content
                }
            }
        ]

    # 1. Subreddit matcher: e.g. "open r/kolkata subreddit", "go to r/news"
    sub_match = re.search(r"\br/([a-zA-Z0-9_]+)\b", lower)
    if sub_match:
        sub_name = sub_match.group(1)
        url = f"https://www.reddit.com/r/{sub_name}"
        return [
            {"title": f"Open r/{sub_name}", "description": f"Navigate to {url}", "tool": "browser_navigate", "args": {"url": url}},
        ]

    # 2. Direct URLs (e.g. "navigate to https://news.ycombinator.com", "open github.com/foo")
    url_match = re.search(r"\b(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.(?:com|org|io|net|dev|edu|gov)(?:/[^\s]*)?)\b", goal)
    if url_match and any(w in lower for w in ("open", "go", "navigate", "visit", "browse", "launch")):
        raw_url = url_match.group(1)
        url = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
        return [
            {"title": f"Navigate to {raw_url}", "description": f"Open {url} in browser", "tool": "browser_navigate", "args": {"url": url}},
        ]

    # 3. Known popular websites
    COMMON_SITES = {
        "youtube": "https://www.youtube.com",
        "reddit": "https://www.reddit.com",
        "github": "https://www.github.com",
        "twitter": "https://www.x.com",
        "x.com": "https://www.x.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "linkedin": "https://www.linkedin.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
        "amazon": "https://www.amazon.com",
    }
    has_action_intent = any(w in lower for w in ("create", "make", "send", "post", "add", "search", "draft", "schedule", "play", "pause", "issue", "message", "email", "mail", "task", "event", "meeting", "track", "music"))
    if not has_action_intent and any(w in lower for w in ("open", "go to", "navigate to", "visit", "launch")):
        for site_name, site_url in COMMON_SITES.items():
            if re.search(rf"\b{site_name}\b", lower):
                return [
                    {"title": f"Open {site_name.capitalize()}", "description": f"Navigate to {site_url}", "tool": "browser_navigate", "args": {"url": site_url}},
                ]

    # 4. Google Form creation & automation
    if any(w in lower for w in ("google form", "google forms", "forms.new", "gform")) or ("form" in lower and any(w in lower for w in ("make", "create", "build", "new", "automate", "automation"))):
        return _build_google_forms_plan(goal)

    # 5. Email Composition & Sending (Gmail API Connector first, Webmail fallback second)
    if any(w in lower for w in ("email", "mail", "gmail")) and any(w in lower for w in ("send", "compose", "write", "draft")):
        to_match = re.search(r"\bto\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9_]+)\b", goal, re.IGNORECASE)
        to_email = to_match.group(1) if to_match else "recipient@example.com"

        cc_match = re.search(r"\bcc\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9_]+)\b", goal, re.IGNORECASE)
        cc_email = cc_match.group(1) if cc_match else None

        bcc_match = re.search(r"\bbcc\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9_]+)\b", goal, re.IGNORECASE)
        bcc_email = bcc_match.group(1) if bcc_match else None

        # Smart compose email subject and body
        subject_text, body_text = await _compose_smart_email(goal, to_email, sender_name=user_name)

        # Check if Gmail API connector is connected in tool registry
        from backend.agent.tools.registry import tool_registry
        if any(w in lower for w in ("save as draft", "save draft", "to drafts")) and tool_registry.has("gmail_create_draft"):
            return [
                {
                    "title": f"Create Draft via Gmail API ({to_email})",
                    "description": f"Create draft email to {to_email} with subject '{subject_text}'",
                    "tool": "gmail_create_draft",
                    "args": {"to": to_email, "subject": subject_text, "body": body_text},
                    "risk_level": "SAFE",
                }
            ]
        elif tool_registry.has("gmail_send_email"):
            return [
                {
                    "title": f"Send Email via Gmail API ({to_email})",
                    "description": f"Send email to {to_email} with subject '{subject_text}'",
                    "tool": "gmail_send_email",
                    "args": {"to": to_email, "subject": subject_text, "body": body_text},
                    "risk_level": "PRIVILEGED",
                }
            ]

        # Fallback to structured browser automation ONLY if no email connector is connected
        plan_steps = [
            {"title": "Open Gmail", "description": "Navigate to Gmail", "tool": "browser_navigate", "args": {"url": "https://mail.google.com"}},
            {"title": "Wait for Gmail", "description": "Allow Gmail to load", "tool": "browser_wait", "args": {"timeout_seconds": 2.0}},
            {"title": "Click Compose", "description": "Click Compose button", "tool": "browser_click", "args": {"selector": "div[role='button'][gh='cm'], [aria-label*='Compose' i]", "text": "Compose"}},
            {"title": "Enter Recipient", "description": f"Type To recipient: {to_email}", "tool": "browser_type", "args": {"selector": "input[aria-label*='To recipients' i], input[name='to'], div[aria-label*='To' i] input", "text": to_email, "press_enter": True}},
        ]

        if cc_email:
            plan_steps.append({"title": "Click Add Cc", "description": "Click Cc button", "tool": "browser_click", "args": {"selector": "span[role='button'][aria-label*='Add Cc' i], [aria-label*='Cc' i]", "text": "Cc"}})
            plan_steps.append({"title": "Enter Cc Recipient", "description": f"Type Cc recipient: {cc_email}", "tool": "browser_type", "args": {"selector": "input[aria-label*='Cc recipients' i], input[name='cc']", "text": cc_email, "press_enter": True}})

        if bcc_email:
            plan_steps.append({"title": "Click Add Bcc", "description": "Click Bcc button", "tool": "browser_click", "args": {"selector": "span[role='button'][aria-label*='Add Bcc' i], [aria-label*='Bcc' i]", "text": "Bcc"}})
            plan_steps.append({"title": "Enter Bcc Recipient", "description": f"Type Bcc recipient: {bcc_email}", "tool": "browser_type", "args": {"selector": "input[aria-label*='Bcc recipients' i], input[name='bcc']", "text": bcc_email, "press_enter": True}})

        plan_steps.append({"title": "Enter Subject", "description": f"Type Subject: {subject_text}", "tool": "browser_type", "args": {"selector": "input[name='subjectbox'], input[aria-label*='Subject' i]", "text": subject_text}})
        plan_steps.append({"title": "Enter Email Body", "description": "Type message content into body", "tool": "browser_type", "args": {"selector": "div[role='textbox'][aria-label*='Message Body' i], div[contenteditable='true'][aria-label*='Body' i]", "text": body_text}})

        if "send" in lower:
            plan_steps.append({"title": "Send Email", "description": "Click Send button", "tool": "browser_click", "args": {"selector": "div[role='button'][data-tooltip*='Send' i], div[role='button'][aria-label*='Send' i]", "text": "Send"}})

        return plan_steps

    # 5.1 Calendar & Schedule queries (Google Calendar API)
    if any(w in lower for w in ("calendar", "meeting", "events", "schedule")) and any(w in lower for w in ("check", "list", "view", "what", "show", "upcoming", "my")):
        from backend.agent.tools.registry import tool_registry
        if tool_registry.has("calendar_list_events"):
            return [{
                "title": "Check Upcoming Calendar Events",
                "description": "Fetch upcoming events from Google Calendar API",
                "tool": "calendar_list_events",
                "args": {"max_results": 10},
            }]

    # 6. Date & Time queries
    if any(w in lower for w in ("date", "time", "clock", "what day", "what time", "today")):
        return [{
            "title": "Check current date and time",
            "description": "Fetch system date, time, and timezone.",
            "tool": "get_current_time",
            "args": {}
        }]

    # 7. Excel / XLSX Spreadsheet generation
    if any(w in lower for w in ("excel", "xlsx", "spreadsheet", "csv")) and any(w in lower for w in ("write", "create", "make", "generate", "build", "save", "export", "file", "top", "list")):
        filename = "spreadsheet.xlsx"
        if "champions league" in lower or "goal scorers" in lower or "top scorers" in lower:
            filename = "ChampionsLeagueTopScorers.xlsx"
        elif "expense" in lower or "budget" in lower:
            filename = "expenses.xlsx"
        else:
            for word in goal.split():
                clean_w = word.strip("\",';:")
                if clean_w.lower().endswith(".xlsx") or clean_w.lower().endswith(".csv"):
                    filename = clean_w
                    break

        has_explicit = False
        target_path = ""
        # Check if user explicitly specified a save location in prompt
        for kw in ("desktop/", "documents/", "c:", "d:", "save to", "save in", "stored in", "put in"):
            if kw in lower:
                has_explicit = True
                break

        if has_explicit:
            target_path = f"Desktop/{filename}" if ("desktop" in lower or "/" not in filename) else filename

        if "chess" in lower:
            filename = "Top10ChessPlayers.xlsx"
            values = [
                ["Rank", "Player", "FIDE Rating", "Country", "Title"],
                [1, "Magnus Carlsen", 2832, "Norway", "Grandmaster"],
                [2, "Hikaru Nakamura", 2802, "United States", "Grandmaster"],
                [3, "Fabiano Caruana", 2798, "United States", "Grandmaster"],
                [4, "Arjun Erigaisi", 2797, "India", "Grandmaster"],
                [5, "Gukesh D", 2794, "India", "Grandmaster"],
                [6, "Nodirbek Abdusattorov", 2783, "Uzbekistan", "Grandmaster"],
                [7, "Alireza Firouzja", 2767, "France", "Grandmaster"],
                [8, "Wei Yi", 2762, "China", "Grandmaster"],
                [9, "Ian Nepomniachtchi", 2758, "Russia", "Grandmaster"],
                [10, "Wesley So", 2751, "United States", "Grandmaster"]
            ]
        elif "champions league" in lower or "goal scorers" in lower or "top scorers" in lower:
            values = [
                ["Rank", "Player", "Goals", "Clubs"],
                [1, "Cristiano Ronaldo", 140, "Manchester United, Real Madrid, Juventus"],
                [2, "Lionel Messi", 129, "Barcelona, Paris Saint-Germain"],
                [3, "Robert Lewandowski", 94, "Borussia Dortmund, Bayern Munich, Barcelona"],
                [4, "Karim Benzema", 90, "Lyon, Real Madrid"],
                [5, "Raúl González", 71, "Real Madrid, Schalke 04"],
                [6, "Ruud van Nistelrooy", 56, "PSV, Manchester United, Real Madrid"],
                [7, "Thomas Müller", 54, "Bayern Munich"],
                [8, "Thierry Henry", 50, "Monaco, Arsenal, Barcelona"],
                [9, "Kylian Mbappé", 49, "Monaco, Paris Saint-Germain, Real Madrid"],
                [10, "Zlatan Ibrahimović", 48, "Ajax, Juventus, Inter, Barcelona, AC Milan, PSG, Man Utd"]
            ]
        else:
            words = [w.capitalize() for w in goal.split() if w.lower() not in ("make", "create", "write", "excel", "file", "for", "a", "an", "the", "of", "top", "list", "spreadsheet", "table", "please", "generate")]
            topic = " ".join(words) or "Data Analysis"
            values = [
                ["Rank", "Title / Name", "Metric / Score", "Category"],
                [1, f"Top Item 1 for {topic}", 98, "Category A"],
                [2, f"Top Item 2 for {topic}", 94, "Category A"],
                [3, f"Top Item 3 for {topic}", 91, "Category B"],
                [4, f"Top Item 4 for {topic}", 87, "Category B"],
                [5, f"Top Item 5 for {topic}", 85, "Category C"]
            ]

        col_count = len(values[0]) if values else 1
        last_col = chr(ord('A') + col_count - 1)

        plan = [
            {"title": "Create Spreadsheet", "description": f"Initialize in-memory spreadsheet for {filename}", "tool": "spreadsheet_create", "args": {"path": target_path, "initial_sheet": "Sheet1"}},
            {"title": "Populate Data", "description": f"Write table rows into {filename}", "tool": "spreadsheet_write_range", "args": {"start_cell": "A1", "values": values, "sheet": "Sheet1"}},
            {"title": "Format Headers", "description": "Apply bold style and header fill", "tool": "spreadsheet_format_range", "args": {"range": f"A1:{last_col}1", "bold": True, "fill_color": "1F4E78", "color": "FFFFFF", "sheet": "Sheet1"}},
            {"title": "Create Table", "description": "Convert range into Excel table", "tool": "spreadsheet_create_table", "args": {"range": f"A1:{last_col}{len(values)}", "name": "DataTable", "sheet": "Sheet1"}},
        ]

        if not has_explicit:
            plan.append({
                "title": "Ask User for Save Location",
                "description": f"Prompt user to specify target save folder or path for {filename}",
                "tool": "ask_user",
                "args": {
                    "prompt": f"Where would you like to save the Excel file ({filename})?",
                    "options": [f"Browse in File Explorer...", f"Desktop/{filename}", f"Documents/{filename}"],
                    "placeholder": f"Click 'Browse in File Explorer...' or type custom file path..."
                }
            })

        plan.extend([
            {"title": "Save Spreadsheet", "description": f"Save XLSX file to destination", "tool": "spreadsheet_save", "args": {"path": target_path}},
            {"title": "Verify Spreadsheet", "description": "Verify saved XLSX file non-emptiness", "tool": "spreadsheet_verify", "args": {"path": target_path, "min_rows": 2}},
        ])
        return plan

    # 8. Document & Research Report Generation Fallback
    if any(w in lower for w in ("docx", "word doc", "word document", "word file", "word report", "report in word", "pdf document", "excel document", "spreadsheet report", "csv report")) and any(w in lower for w in ("write", "create", "make", "generate", "build", "save", "export", "file", "report")):
        # If this is any kind of research, analysis, topic overview, or substantive inquiry:
        if any(w in lower for w in ("research", "study", "analysis", "in-depth", "deep", "investigate", "history", "industrialization", "market", "economy", "citations", "sources", "overview of", "summary of", "findings")):
            clean_topic = _extract_clean_research_topic(goal)
            fmt, req_fmt, primary_ext = _detect_research_format(goal)

            if not _has_explicit_research_params(goal):
                clarification_msg = await _build_deep_research_clarification_response(clean_topic, goal)
                return [
                    {
                        "title": f"Research Scope & Focus Options ({clean_topic.title()})",
                        "description": f"Prompt user for depth level and focal subtopics for research on '{clean_topic}'",
                        "tool": "ai_response",
                        "args": {
                            "answer": clarification_msg
                        }
                    }
                ]

            subtopics = _extract_subtopics_from_prompt(goal)
            filename = re.sub(r"[^\w\s-]", "", clean_topic)
            filename = "_".join(filename.split()[:7]) or "Research_Report"
            target_path = f"Desktop/{filename}.{primary_ext}"

            depth_val = "exhaustive" if "exhaustive" in lower else "deep"

            args = {
                "topic": clean_topic,
                "output_format": fmt,
                "output_path": target_path,
                "depth": depth_val,
            }
            if subtopics:
                args["subtopics"] = subtopics
            if req_fmt:
                args["requested_format"] = req_fmt

            desc = (
                f"Autonomous deep web research on '{clean_topic}' compiled into {fmt.upper()} (note: proprietary .{req_fmt} cannot be generated)"
                if req_fmt
                else f"Gather live sources and conduct in-depth multi-source research on '{clean_topic}' into {fmt.upper()}"
            )

            return [
                {
                    "title": f"Autonomous Deep Web Research ({clean_topic.title()})",
                    "description": desc,
                    "tool": "deep_research",
                    "args": args,
                }
            ]

        filename = "document.docx"
        for word in goal.split():
            clean_w = word.strip("\",';:")
            if clean_w.lower().endswith(".docx"):
                filename = clean_w
                break

        title = "Generated Report"
        if "python" in lower:
            title = "Python Programming Report"
            filename = "PythonReport.docx"
        elif "ai" in lower or "artificial intelligence" in lower:
            title = "Artificial Intelligence Report"
            filename = "AI_Report.docx"

        has_explicit = False
        target_path = ""
        for kw in ("desktop/", "documents/", "c:", "d:", "save to", "save in", "stored in", "put in"):
            if kw in lower:
                has_explicit = True
                break

        if has_explicit:
            target_path = f"Desktop/{filename}" if ("desktop" in lower or "/" not in filename) else filename

        plan = [
            {"title": "Create Document", "description": f"Initialize in-memory DOCX document for {filename}", "tool": "document_create", "args": {"path": target_path}},
            {"title": "Add Title", "description": f"Add document title: {title}", "tool": "document_add_title", "args": {"text": title}},
            {"title": "Add Section", "description": "Add Executive Summary section", "tool": "document_add_heading", "args": {"text": "Executive Summary", "level": 1}},
            {"title": "Add Content", "description": "Add section narrative", "tool": "document_add_paragraph", "args": {"text": f"This report provides an automated overview of {title}."}},
        ]

        if not has_explicit:
            plan.append({
                "title": "Ask User for Save Location",
                "description": f"Prompt user to specify target save folder or path for {filename}",
                "tool": "ask_user",
                "args": {
                    "prompt": f"Where would you like to save the Word document ({filename})?",
                    "options": [f"Browse in File Explorer...", f"Desktop/{filename}", f"Documents/{filename}"],
                    "placeholder": f"Click 'Browse in File Explorer...' or type custom file path..."
                }
            })

        plan.extend([
            {"title": "Save Document", "description": "Save DOCX file to destination", "tool": "document_save", "args": {"path": target_path}},
            {"title": "Verify Document", "description": "Verify saved DOCX file", "tool": "document_verify", "args": {"path": target_path, "min_paragraphs": 1}},
        ])
        return plan

    return []


async def _generate_spreadsheet_data(goal: str, has_api_key: bool) -> tuple[str, list[list[Any]]]:
    """
    Dynamically research / generate accurate tabular data for any spreadsheet request.
    Returns (filename, values_matrix).
    """
    import json
    import re
    lower = goal.lower()

    filename = "spreadsheet.xlsx"
    for word in goal.split():
        clean_w = word.strip("\",';:()")
        if clean_w.lower().endswith(".xlsx") or clean_w.lower().endswith(".csv"):
            filename = clean_w
            break

    if filename == "spreadsheet.xlsx":
        if "chess" in lower:
            filename = "Top10ChessPlayers.xlsx"
        elif "champions league" in lower or "goal scorers" in lower:
            filename = "ChampionsLeagueTopScorers.xlsx"
        elif "expense" in lower or "budget" in lower:
            filename = "ExpenseReport.xlsx"
        else:
            words = [re.sub(r'[^a-zA-Z0-9]', '', w).capitalize() for w in goal.split() if w.lower() not in ("make", "create", "write", "excel", "file", "for", "a", "an", "the", "of", "top", "list", "spreadsheet", "table", "please", "generate")]
            clean_topic = "".join(words[:4]) or "DataReport"
            filename = f"{clean_topic}.xlsx"

    values = []
    if has_api_key:
        try:
            prompt = (
                f"The user requested a spreadsheet for: '{goal}'.\n"
                "Generate an accurate, comprehensive, up-to-date 2D JSON matrix for this spreadsheet request.\n"
                "Include a clear header row with appropriate column titles.\n"
                "If rankings, numbers, statistics, ratings, or facts are requested, provide accurate real-world data.\n"
                "Format strictly as a valid JSON array of arrays (no commentary, no markdown code blocks outside json):\n"
                "[[\"Header1\", \"Header2\", \"Header3\"], [val1, val2, val3], ...]"
            )
            res = await ainvoke_with_dynamic_switch(
                [
                    SystemMessage(content="You are NEXUS Data Research Engine. Generate accurate 2D JSON matrix data for spreadsheets."),
                    HumanMessage(content=prompt)
                ],
                operation="reasoning",
                temperature=0.2
            )
            raw = res.content.strip()
            if "```" in raw:
                raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
            if "[" in raw and "]" in raw:
                start = raw.index("[")
                end = raw.rindex("]") + 1
                parsed = json.loads(raw[start:end])
                if isinstance(parsed, list) and len(parsed) > 1 and isinstance(parsed[0], list):
                    values = parsed
        except Exception as e:
            logger.warning(f"Dynamic spreadsheet LLM data generation failed: {e}")

    if not values:
        if "chess" in lower:
            values = [
                ["Rank", "Player", "FIDE Rating", "Country", "Title"],
                [1, "Magnus Carlsen", 2832, "Norway", "Grandmaster"],
                [2, "Hikaru Nakamura", 2802, "United States", "Grandmaster"],
                [3, "Fabiano Caruana", 2798, "United States", "Grandmaster"],
                [4, "Arjun Erigaisi", 2797, "India", "Grandmaster"],
                [5, "Gukesh D", 2794, "India", "Grandmaster"],
                [6, "Nodirbek Abdusattorov", 2783, "Uzbekistan", "Grandmaster"],
                [7, "Alireza Firouzja", 2767, "France", "Grandmaster"],
                [8, "Wei Yi", 2762, "China", "Grandmaster"],
                [9, "Ian Nepomniachtchi", 2758, "Russia", "Grandmaster"],
                [10, "Wesley So", 2751, "United States", "Grandmaster"]
            ]
        elif "champions league" in lower or "goal scorers" in lower or "top scorers" in lower:
            values = [
                ["Rank", "Player", "Goals", "Clubs"],
                [1, "Cristiano Ronaldo", 140, "Manchester United, Real Madrid, Juventus"],
                [2, "Lionel Messi", 129, "Barcelona, Paris Saint-Germain"],
                [3, "Robert Lewandowski", 94, "Borussia Dortmund, Bayern Munich, Barcelona"],
                [4, "Karim Benzema", 90, "Lyon, Real Madrid"],
                [5, "Raúl González", 71, "Real Madrid, Schalke 04"],
                [6, "Ruud van Nistelrooy", 56, "PSV, Manchester United, Real Madrid"],
                [7, "Thomas Müller", 54, "Bayern Munich"],
                [8, "Thierry Henry", 50, "Monaco, Arsenal, Barcelona"],
                [9, "Kylian Mbappé", 49, "Monaco, Paris Saint-Germain, Real Madrid"],
                [10, "Zlatan Ibrahimović", 48, "Ajax, Juventus, Inter, Barcelona, AC Milan, PSG, Man Utd"]
            ]
        else:
            values = [
                ["Item", "Description", "Value", "Category"],
                ["Data Row 1", f"Primary entry for {goal}", 100, "Active"],
                ["Data Row 2", f"Secondary entry for {goal}", 200, "Active"],
                ["Total", "Summary total", "=SUM(C2:C3)", "Summary"]
            ]

    return filename, values


async def _build_dynamic_spreadsheet_plan(goal: str, has_api_key: bool) -> list[dict]:
    lower = goal.lower()
    filename, values = await _generate_spreadsheet_data(goal, has_api_key)

    has_explicit = False
    target_path = ""
    for kw in ("desktop/", "documents/", "c:", "d:", "save to", "save in", "stored in", "put in"):
        if kw in lower:
            has_explicit = True
            break

    if has_explicit:
        target_path = f"Desktop/{filename}" if ("desktop" in lower or "/" not in filename) else filename

    col_count = len(values[0]) if values else 1
    last_col = chr(ord('A') + col_count - 1)

    plan = [
        {"title": "Create Spreadsheet", "description": f"Initialize in-memory spreadsheet for {filename}", "tool": "spreadsheet_create", "args": {"path": target_path, "initial_sheet": "Sheet1"}},
        {"title": "Populate Data", "description": f"Write {len(values)} rows into {filename}", "tool": "spreadsheet_write_range", "args": {"start_cell": "A1", "values": values, "sheet": "Sheet1"}},
        {"title": "Format Headers", "description": "Apply bold style and header fill", "tool": "spreadsheet_format_range", "args": {"range": f"A1:{last_col}1", "bold": True, "fill_color": "1F4E78", "color": "FFFFFF", "sheet": "Sheet1"}},
        {"title": "Create Table", "description": "Convert range into Excel table", "tool": "spreadsheet_create_table", "args": {"range": f"A1:{last_col}{len(values)}", "name": "DataTable", "sheet": "Sheet1"}},
    ]

    if not has_explicit:
        plan.append({
            "title": "Ask User for Save Location",
            "description": f"Prompt user to specify target save folder or path for {filename}",
            "tool": "ask_user",
            "args": {
                "prompt": f"Where would you like to save the Excel file ({filename})?",
                "options": [f"Browse in File Explorer...", f"Desktop/{filename}", f"Documents/{filename}"],
                "placeholder": f"Click 'Browse in File Explorer...' or type custom file path..."
            }
        })

    plan.extend([
        {"title": "Save Spreadsheet", "description": f"Save XLSX file to destination", "tool": "spreadsheet_save", "args": {"path": target_path}},
        {"title": "Verify Spreadsheet", "description": "Verify saved XLSX file non-emptiness", "tool": "spreadsheet_verify", "args": {"path": target_path, "min_rows": 2}},
    ])
    return plan


def _extract_clean_presentation_topic(goal: str) -> str:
    """Extract clean presentation topic by stripping leading command directives and trailing save clauses."""
    import re
    topic = goal.strip()
    # Strip leading directive: e.g. "make a power point presentation on", "create a ppt about", "generate slides for"
    topic = re.sub(
        r"^(?:please\s+)?(?:do|make|create|generate|write|build|prepare)?\s*"
        r"(?:a\s+|an\s+|the\s+|some\s+)?(?:powerpoint|power\s+point|presentation|slides?|slide\s+deck|ppt|pptx)?"
        r"(?:\s+(?:presentation|slides?|slide\s+deck|file|deck))?"
        r"(?:\s+(?:on|about|regarding|for|of|with\s+topic))\s*",
        "",
        topic,
        flags=re.IGNORECASE
    )
    # Strip explicit trailing save/store directives: e.g. "and save to desktop", "save in documents", "stored in downloads"
    topic = re.sub(
        r"\s*(?:and\s+)?(?:save|put|store|export)\s+(?:it\s+)?(?:to|in|on)\s+(?:desktop|documents|downloads|file\s+explorer|folder).*$",
        "",
        topic,
        flags=re.IGNORECASE
    )
    # Strip trailing punctuation or "please"
    topic = re.sub(r"[\s,;.]*(?:please)?$", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"^(?:the|a|an)\s+", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\s+", " ", topic).strip()
    return topic if topic else "Presentation"



async def _build_dynamic_presentation_plan(goal: str, has_api_key: bool) -> list[dict]:
    """Build multi-step plan for PowerPoint presentation creation, interactive storage selection, and verification."""
    import re
    lower = goal.lower()
    topic = _extract_clean_presentation_topic(goal)
    sanitized = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")
    if not sanitized:
        sanitized = "Presentation"
    filename = f"{sanitized}.pptx"

    has_explicit = False
    target_path = ""
    for kw in ("desktop/", "documents/", "downloads/", "c:", "d:", "save to", "save in", "stored in", "put in"):
        if kw in lower:
            has_explicit = True
            break

    if has_explicit:
        target_path = f"Desktop/{filename}" if ("desktop" in lower or "/" not in filename) else filename

    plan = [
        {
            "title": f"Create Presentation on {topic}",
            "description": f"Generate 16:9 widescreen PowerPoint presentation on '{topic}' with relevant web pictures",
            "tool": "presentation_create",
            "args": {"topic": topic, "theme": "executive_navy", "num_slides": 6, "include_images": True},
        },
    ]

    if not has_explicit:
        plan.append({
            "title": "Choose Storage Location",
            "description": f"Prompt user where to store the PowerPoint presentation ({filename})",
            "tool": "ask_user",
            "args": {
                "prompt": f"PowerPoint presentation created on '{topic}'! Where would you like to store the presentation ({filename})?",
                "options": ["Desktop", "Documents", "Downloads", "Choose via File Explorer..."],
                "placeholder": f"Select destination or enter custom path (e.g. Desktop/{filename})...",
                "parameter_name": "target_path",
            }
        })

    plan.extend([
        {
            "title": "Save Presentation",
            "description": f"Save PPTX file to destination and reveal in File Explorer",
            "tool": "presentation_save",
            "args": {
                "path": target_path or "{{target_path}}",
                "default_filename": filename,
                "topic": topic,
            },
        },
        {
            "title": "Verify Presentation",
            "description": "Verify saved PPTX file integrity and slides",
            "tool": "presentation_verify",
            "args": {
                "path": target_path or "{{target_path}}",
                "min_slides": 4,
                "topic": topic,
            },
        },
    ])
    return plan



def _ensure_step_fields(raw_steps: list[dict]) -> list[dict]:
    """Guarantee every plan step dict has all required PlanStep fields.
    Fast-path helpers return minimal dicts without id/risk_level/status/result/error,
    which causes a KeyError in permission_gate_node (step["id"]).
    This helper is idempotent — already-complete steps pass through unchanged.
    """
    normalised = []
    for item in (raw_steps or []):
        if item.get("id") and item.get("risk_level") and item.get("status"):
            normalised.append(item)
            continue
        tool = item.get("tool", "ai_response")
        args = item.get("args", {})
        if not item.get("risk_level"):
            if tool == "run_command":
                risk = classify_command(args.get("command", "")).value
            elif tool in ("write_file", "delete_file"):
                risk = classify_file_op("delete" if tool == "delete_file" else "write").value
            elif tool in ("read_file", "list_directory", "search_files", "browser_get_tabs", "browser_inspect"):
                risk = RiskLevel.READ_ONLY.value
            elif tool in ("browser_execute_js", "click_mouse", "type_text", "press_hotkey", "press_key"):
                risk = RiskLevel.MODIFYING.value
            else:
                risk = RiskLevel.SAFE.value
        else:
            risk = item["risk_level"]
        normalised.append({
            "id": item.get("id") or f"step-{uuid.uuid4().hex[:6]}",
            "title": item.get("title", "Execute action"),
            "description": item.get("description", ""),
            "tool": tool,
            "args": args,
            "risk_level": risk,
            "status": item.get("status", "pending"),
            "result": item.get("result"),
            "error": item.get("error"),
        })
    return normalised


_normalise_plan = _ensure_step_fields


async def planner_node(state: NexusState) -> dict:
    # 0. Fast-Path & Plan Cache Check: If plan is already formulated, return it with 0 LLM calls!
    existing_plan = state.get("plan")
    if existing_plan and len(existing_plan) > 0:
        return {
            "plan": existing_plan,
            "current_step": 0,
            "execution_status": "planning",
        }

    goal = state.get("goal") or state.get("user_input", "")
    intent = state.get("intent", "general")
    has_api_key = bool(get_groq_api_key() or get_gemma_api_key())

    # ── Task Scheduling Fast-Path Match (Prioritized over immediate execution) ──
    try:
        from backend.services.schedule_parser import schedule_parser
        raw_prompt = goal or state.get("user_input", "")
        sched_res = await schedule_parser.parse(raw_prompt)
        if sched_res and sched_res.is_schedule:
            if sched_res.is_ambiguous:
                clarify_step = {
                    "id": f"sched-clarify-{uuid.uuid4().hex[:6]}",
                    "title": "Clarify Schedule Timing",
                    "description": sched_res.clarification_question or "When would you like to schedule this?",
                    "tool": "ask_user",
                    "args": {
                        "prompt": sched_res.clarification_question or "When would you like to schedule this?",
                        "placeholder": "e.g. Tomorrow at 9:00 AM",
                        "parameter_name": "schedule_timing",
                    },
                    "risk_level": "low",
                    "status": "pending",
                }
                return {
                    "plan": [clarify_step],
                    "current_step": 0,
                    "execution_status": "executing",
                    "selected_model": "schedule-clarify-fastpath",
                }
            else:
                next_str = sched_res.next_run_at.strftime('%A at %I:%M %p') if sched_res.next_run_at else "specified time"
                schedule_step = {
                    "id": f"sched-{uuid.uuid4().hex[:6]}",
                    "title": f"Schedule {sched_res.task_type.capitalize()}: {sched_res.name}",
                    "description": f"Schedule {sched_res.task_type} '{sched_res.name}' to trigger on {next_str}.",
                    "tool": "schedule_task",
                    "args": {
                        "name": sched_res.name,
                        "prompt": sched_res.prompt,
                        "task_type": sched_res.task_type,
                        "schedule_type": sched_res.schedule_type,
                        "schedule_definition": sched_res.schedule_definition,
                        "timezone": sched_res.timezone,
                        "user_id": state.get("user_id"),
                    },
                    "risk_level": "safe",
                    "status": "pending",
                }
                return {
                    "plan": [schedule_step],
                    "current_step": 0,
                    "execution_status": "executing",
                    "selected_model": "schedule-fastpath",
                }
    except Exception as exc:
        logger.debug("Schedule planner fastpath skipped: %s", exc)

    # ── Tier 0: Connected Application / MCP Connectors (Highest Priority) ──
    try:
        connector_priority_plan = await _build_active_connector_priority_plan(goal or state.get("user_input", ""), user_id=state.get("user_id") or "default", user_name=state.get("user_name"))
        if connector_priority_plan:
            norm_plan = _normalise_plan(connector_priority_plan)
            return {
                "plan": norm_plan,
                "current_step": 0,
                "execution_status": "executing",
                "selected_model": "connector-fastpath",
            }
    except Exception as exc:
        logger.debug("Connector fastpath skipped: %s", exc)

    # ── Learned Skill Fast-Path Match ────────────────────────────
    try:
        from backend.database.session import get_session_factory
        session_factory = get_session_factory()
        user_id_val = state.get("user_id")
        if session_factory:
            uid = None
            if user_id_val:
                try:
                    uid = uuid.UUID(str(user_id_val)) if isinstance(user_id_val, str) else user_id_val
                except Exception:
                    uid = None
            if not uid:
                from backend.core.firebase_auth import LOCAL_USER_ID
                uid = LOCAL_USER_ID

            from backend.database.session import safe_db_context
            import asyncio
            async with safe_db_context() as db_session:
                if uid and db_session:
                    from backend.agent.skills.matcher import matcher
                    from backend.agent.skills.runtime import runtime
                    try:
                        matched = await asyncio.wait_for(
                            matcher.match_skill(goal or state.get("user_input", ""), uid, db_session),
                            timeout=3.0,
                        )
                        if not matched and uid != LOCAL_USER_ID:
                            matched = await asyncio.wait_for(
                                matcher.match_skill(goal or state.get("user_input", ""), LOCAL_USER_ID, db_session),
                                timeout=3.0,
                            )
                    except (TimeoutError, asyncio.TimeoutError):
                        logger.debug("[Planner] Learned skill matching timed out (continuing with planner).")
                        matched = None

                    if matched and not matched.is_ambiguous:
                        # Suppress legacy web-automation skills if a real API connector is active
                        skill_name_lower = (matched.skill.name or "").lower()
                        if any(w in skill_name_lower for w in ("email", "mail", "gmail")):
                            from backend.connectors.credentials_store import credentials_store
                            if credentials_store.get_credential("default", "gmail") or credentials_store.get_credential(str(uid), "gmail"):
                                logger.info("[Planner] Suppressing legacy web-automation skill '%s' because Gmail API connector is connected.", matched.skill.name)
                                matched = None

                    if matched and not matched.is_ambiguous:
                        import re
                        # Extract any template parameter names referenced in the recipe steps
                        referenced_params: set[str] = set()
                        raw_steps = (matched.version.steps_json if matched.version else []) or []
                        for step in raw_steps:
                            for val in (step.get("title"), step.get("value_template"), step.get("value"), step.get("url")):
                                if isinstance(val, str):
                                    referenced_params.update(re.findall(r"\{\{([^}]+)\}\}", val))
                            for ref in (step.get("parameter_references") or []):
                                if ref:
                                    referenced_params.add(str(ref))

                        needed = [p for p in referenced_params if p not in matched.resolved_parameters or not matched.resolved_parameters[p]]
                        if not needed and matched.missing_parameters:
                            needed = list(matched.missing_parameters)

                        # Intelligently compose/extract parameters using AI from the natural language prompt
                        if needed:
                            try:
                                from backend.agent.skills.param_extractor import extractor
                                prompt_text = goal or state.get("user_input", "")
                                synthesized = await extractor.synthesize_parameters_with_ai(
                                    user_prompt=prompt_text,
                                    skill_name=matched.skill.name,
                                    parameters_needed=needed,
                                )
                                if synthesized:
                                    matched.resolved_parameters.update(synthesized)
                                    matched.missing_parameters = [p for p in matched.missing_parameters if p not in synthesized]
                                    logger.info("[Planner] Synthesized skill parameters with AI: %s", list(synthesized.keys()))
                            except Exception as syn_err:
                                logger.warning("[Planner] Parameter synthesis error: %s", syn_err)

                        skill_steps = runtime.generate_plan_steps(matched)
                        # Self-healing: if any step was blocked due to missing recorded selectors, reframe dynamically
                        if skill_steps and any(s.get("id", "").startswith("skill-blocked") for s in skill_steps):
                            try:
                                from backend.agent.skills.reframer import reframe_skill_steps
                                blocked_reason = skill_steps[0].get("description", "Skill recipe validation flagged missing selectors.")
                                reframed = await reframe_skill_steps(
                                    goal=goal or state.get("user_input", ""),
                                    user_input=state.get("user_input", ""),
                                    plan=skill_steps,
                                    current_idx=0,
                                    error_context=blocked_reason,
                                    skill_name=matched.skill.name,
                                    skill_id=str(matched.skill.id),
                                    resolved_params=matched.resolved_parameters,
                                )
                                if reframed:
                                    skill_steps = reframed
                            except Exception as ref_err:
                                logger.warning("[Planner] Pre-execution reframing skipped: %s", ref_err)

                        if skill_steps:
                            obs = state.get("observations", []).copy()
                            confidence_pct = int(matched.confidence * 100)
                            match_label = {
                                "exact_trigger": "exact trigger",
                                "semantic_similarity": "semantic match",
                                "ai_intent": "AI intent match",
                            }.get(matched.match_type, matched.match_type)
                            if matched.missing_parameters:
                                obs.append(
                                    f"[Skill Replay] Matched '{matched.skill.name}' v{matched.version.version_number} "
                                    f"via {match_label} ({confidence_pct}%). "
                                    f"Collecting missing inputs: {', '.join(matched.missing_parameters)}."
                                )
                            else:
                                obs.append(
                                    f"[Skill Replay] Dispatching '{matched.skill.name}' v{matched.version.version_number} "
                                    f"via {match_label} ({confidence_pct}%). LLM planner bypassed."
                                )
                            return {
                                "plan": skill_steps,
                                "current_step": 0,
                                "observations": obs,
                                "execution_status": "executing",
                                "selected_model": "skill-replay-fastpath",
                                "skill_id": str(matched.skill.id),
                                "skill_version": matched.version.version_number,
                                "is_replay_mode": True,
                                "resolved_params": matched.resolved_parameters,
                            }
                    elif matched and matched.is_ambiguous and matched.competing_skills:
                        # Two skills match with similar confidence - surface disambiguation to user
                        competitors = matched.competing_skills
                        clarify_step = {
                            "id": f"skill-disambig-{uuid.uuid4().hex[:6]}",
                            "title": "Clarify: Which skill did you mean?",
                            "description": (
                                f"Multiple saved skills match your request. "
                                f"Please select which one to run: {' or '.join(repr(c) for c in competitors)}"
                            ),
                            "tool": "ask_user",
                            "args": {
                                "prompt": "I found multiple skills that match your request. Which one would you like to run?",
                                "options": competitors,
                                "placeholder": "Select a skill or type the name…",
                                "parameter_name": "skill_choice",
                            },
                            "risk_level": RiskLevel.SAFE.value,
                            "status": "pending",
                            "result": None,
                            "error": None,
                        }
                        obs = state.get("observations", []).copy()
                        obs.append(
                            f"[Skill Replay] Ambiguous match between {' and '.join(repr(c) for c in competitors)}. "
                            "Asking user to clarify."
                        )
                        return {
                            "plan": [clarify_step],
                            "current_step": 0,
                            "observations": obs,
                            "execution_status": "executing",
                            "selected_model": "skill-disambiguation",
                        }
    except Exception as exc:
        logger.debug(f"[Planner] Learned skill matching exception: {exc}")

    # Read on_token from global registry (not from state — functions aren't msgpack serializable)
    try:
        from backend.api.nexus import _token_callbacks
        on_token = _token_callbacks.get(task_id)
    except Exception:
        on_token = None

    lower_goal = goal.lower().strip()
    is_presentation_creation_query = (
        any(w in lower_goal for w in ("powerpoint", "power point", "presentation", "slides", "ppt", "pptx", "slide deck")) and
        any(w in lower_goal for w in ("make", "create", "write", "save", "generate", "build", "export", "deck", "slides", "topic", "for", "on", "about", "presentation"))
    )
    is_excel_creation_query = (
        any(w in lower_goal for w in ("excel", "xlsx", "spreadsheet", "csv")) and
        any(w in lower_goal for w in ("make", "create", "write", "save", "generate", "build", "export", "top", "list", "file", "for"))
    )
    is_docx_creation_query = (
        any(w in lower_goal for w in ("docx", "word doc", "word document", "word file", "word report", "report in word")) and
        any(w in lower_goal for w in ("make", "create", "write", "save", "generate", "build", "export", "report", "file", "for"))
    )
    is_file_creation_query = (
        any(w in lower_goal for w in ("make", "create", "write", "save", "note", "add")) and
        any(w in lower_goal for w in ("file", "text", "notes", "txt", "doc", "script", "desktop"))
    )

    active_target = state.get("active_target") or {}
    active_context = state.get("active_context") or {}
    target_type = str(active_target.get("target_type") or "").lower()
    target_app = str(active_target.get("application") or "").lower()

    is_excel_active = (target_type == "excel" or "excel" in target_app)
    excel_copilot_keywords = (
        "sum", "average", "avg", "total", "count", "counta", "sumif", "averageif",
        "xlookup", "vlookup", "sort", "filter", "pivot", "highlight",
        "conditional format", "remove duplicate", "split", "flash fill", "formula"
    )
    is_excel_copilot_request = (is_excel_active and not is_presentation_creation_query and not (is_excel_creation_query and "create" in lower_goal and "file" in lower_goal)) or (
        any(w in lower_goal for w in excel_copilot_keywords) and any(w in lower_goal for w in ("sales", "column", "table", "revenue", "row", "sheet", "cell", "excel")) and not is_presentation_creation_query and not is_excel_creation_query
    )

    if is_presentation_creation_query:
        plan_data = await _build_dynamic_presentation_plan(goal, has_api_key)
    elif is_excel_copilot_request:
        from backend.agent.tools.excel_copilot.planner import build_excel_copilot_plan
        copilot_steps = build_excel_copilot_plan(goal, active_target=active_target, active_context=active_context)
        if copilot_steps:
            plan_data = copilot_steps
        elif is_excel_creation_query or (intent == "file_op" and any(w in lower_goal for w in ("excel", "xlsx", "spreadsheet", "csv"))):
            plan_data = await _build_dynamic_spreadsheet_plan(goal, has_api_key)
        else:
            plan_data = None
    elif is_excel_creation_query or (intent == "file_op" and any(w in lower_goal for w in ("excel", "xlsx", "spreadsheet", "csv"))):
        plan_data = await _build_dynamic_spreadsheet_plan(goal, has_api_key)
    else:

        active_target = state.get("active_target")
        active_context = state.get("active_context")

        connector_priority_plan = await _build_active_connector_priority_plan(goal, user_id=state.get("user_id") or "default", user_name=state.get("user_name"))
        if connector_priority_plan:
            plan_data = connector_priority_plan
        else:
            # Try ultra-fast deterministic compiler first (<1ms)
            plan_data = await _try_fast_path_plan(
                goal,
                intent,
                active_target=active_target,
                active_context=active_context,
                state_messages=state.get("messages"),
                user_name=state.get("user_name"),
            )


        if not plan_data and has_api_key and intent == "question":
            # Direct Ultra-Fast Knowledge Answer Engine on Groq LPUs (<500ms)
            q_messages = [
                SystemMessage(content=(
                    "You are NEXUS, an intelligent and helpful AI assistant. "
                    "Provide a thorough, accurate, and beautifully structured markdown response with clear headings, bullet points, and clean typography. "
                    "Do not mention internal schemas or tools."
                )),
                HumanMessage(content=goal or state.get("user_input", "")),
            ]
            try:
                response = await ainvoke_with_dynamic_switch(
                    q_messages,
                    operation="fast",
                    temperature=0.3,
                    max_tokens=800,
                    per_attempt_timeout=6.0,
                )
                ans_text = response.content.strip()
                if ans_text:
                    plan_data = [{
                        "title": "NEXUS Knowledge Response",
                        "description": "Direct response to user question.",
                        "tool": "ai_response",
                        "args": {"answer": ans_text},
                        "risk_level": "SAFE",
                        "status": "pending",
                    }]
            except Exception as q_err:
                logger.warning("[Planner] Fast question engine error: %s", q_err)

        if not plan_data and has_api_key:
            target_info = ""
            if active_target:
                target_info = f"\nACTIVE TARGET: {active_target.get('application')} - {active_target.get('window_title')}"
                if active_context and active_context.get("details"):
                    target_info += f"\nACTIVE TARGET CONTEXT: {json.dumps(active_context.get('details'))}"

            try:
                connector_prompt_text = ""
                try:
                    from backend.connectors.manager import connector_manager
                    connector_prompt_text = connector_manager.get_tool_prompt_additions()
                except Exception:
                    pass

                full_planner_prompt = PLANNER_PROMPT + (connector_prompt_text if connector_prompt_text else "")
                messages = [
                    SystemMessage(content=full_planner_prompt),
                    HumanMessage(content=f"Intent: {intent}\nGoal: {goal}{target_info}")
                ]
                response = await ainvoke_with_dynamic_switch(messages, operation="reasoning", temperature=0.1)
                content = response.content.strip()
                if on_token:
                    try:
                        await on_token(content)
                    except Exception:
                        pass
                plan_data = _clean_and_parse_json(content)
                if not plan_data and content and intent in ("question", "general"):
                    plan_data = [{
                        "title": "NEXUS Response",
                        "description": "Direct response to user question.",
                        "tool": "ai_response",
                        "args": {"answer": content},
                        "risk_level": "SAFE",
                    }]
            except Exception as e:
                logger.warning("[Planner] Reasoning LLM call error: %s", e)
                if has_api_key and intent in ("question", "general"):
                    try:
                        ans_msg = await ainvoke_with_dynamic_switch(
                            [
                                SystemMessage(content="You are NEXUS, an intelligent and helpful AI assistant. Answer the user's inquiry clearly and accurately in markdown format."),
                                HumanMessage(content=goal or state.get("user_input", ""))
                            ],
                            operation="fast",
                            temperature=0.3
                        )
                        if ans_msg and ans_msg.content:
                            plan_data = [{
                                "title": "NEXUS Response",
                                "description": "Direct AI response to inquiry.",
                                "tool": "ai_response",
                                "args": {"answer": ans_msg.content.strip()},
                                "risk_level": "SAFE",
                            }]
                    except Exception:
                        plan_data = []
                else:
                    plan_data = []

    lower_goal = goal.lower().strip()
    is_excel_creation_query = (
        any(w in lower_goal for w in ("excel", "xlsx", "spreadsheet", "csv")) and
        any(w in lower_goal for w in ("make", "create", "write", "save", "generate", "build", "export", "top", "list", "file"))
    )
    is_docx_creation_query = (
        any(w in lower_goal for w in ("docx", "word doc", "word document", "word file", "word report", "report in word")) and
        any(w in lower_goal for w in ("make", "create", "write", "save", "generate", "build", "export", "report", "file"))
    )
    is_file_creation_query = (
        any(w in lower_goal for w in ("make", "create", "write", "save", "note", "add")) and
        any(w in lower_goal for w in ("file", "text", "notes", "txt", "doc", "script", "desktop"))
    )

    # Convert any accidental ai_response or text tutorial into direct automation steps (preserving Research Clarifications)
    if plan_data:
        has_ai_response = any(item.get("tool") == "ai_response" for item in plan_data)
        is_research_clarification = any("Research Scope" in item.get("title", "") or "Clarification" in item.get("title", "") for item in plan_data)
        if has_ai_response and not is_research_clarification:
            if is_presentation_creation_query or any(w in lower_goal for w in ("powerpoint", "power point", "presentation", "slides", "ppt", "pptx")):
                plan_data = await _build_dynamic_presentation_plan(goal, has_api_key)
            elif is_excel_creation_query or "excel" in lower_goal or "xlsx" in lower_goal or "spreadsheet" in lower_goal:
                plan_data = await _build_dynamic_spreadsheet_plan(goal, has_api_key)

            elif is_docx_creation_query or "docx" in lower_goal or "word file" in lower_goal or "word doc" in lower_goal:
                fast_docx = await _try_fast_path_plan(goal, "file_op", state_messages=state.get("messages"))
                if fast_docx:
                    plan_data = _ensure_step_fields(fast_docx)
            elif is_file_creation_query:
                for item in plan_data:
                    if item.get("tool") == "ai_response":
                        filename = "music_theory_notes.txt" if "music" in lower_goal else "notes.txt"
                        target_path = f"~/Desktop/{filename}" if "desktop" in lower_goal else filename
                        item["tool"] = "write_file"
                        item["title"] = f"Create {filename}"
                        item["description"] = f"Write notes to {target_path}"
                        item["args"] = {
                            "path": target_path,
                            "content": item.get("args", {}).get("answer", "") or (
                                "Music Theory Notes:\n"
                                "- Scales: Major (W-W-H-W-W-W-H), Natural Minor (W-H-W-W-H-W-W)\n"
                                "- Triads: Major (1-3-5), Minor (1-b3-5), Diminished (1-b3-b5), Augmented (1-3-#5)\n"
                                "- Seventh Chords: Major 7th (1-3-5-7), Dominant 7th (1-3-5-b7), Minor 7th (1-b3-5-b7)\n"
                                "- Circle of Fifths: C, G, D, A, E, B, F#, C#, Ab, Eb, Bb, F\n"
                            )
                        }

    if not plan_data:
        # Fallback plan generation based on intent and keywords
        if any(w in lower_goal for w in ("date", "time", "clock", "what day", "what time", "today")):
            plan_data = [{
                "title": "Check current date and time",
                "description": "Fetch system date, time, and timezone.",
                "tool": "get_current_time",
                "args": {}
            }]
        elif any(w in lower_goal for w in ("google form", "google forms", "forms.new", "gform")) or ("form" in lower_goal and any(w in lower_goal for w in ("make", "create", "build", "new", "automate", "automation", "containing", "name", "phone", "email"))):
            plan_data = _build_google_forms_plan(goal)
        elif is_excel_creation_query or "excel" in lower_goal or "xlsx" in lower_goal or "spreadsheet" in lower_goal:
            plan_data = await _build_dynamic_spreadsheet_plan(goal, has_api_key)
        elif is_docx_creation_query or "docx" in lower_goal or "word doc" in lower_goal or "word file" in lower_goal:
            fast_docx = await _try_fast_path_plan(goal, "file_op", state_messages=state.get("messages"))
            if fast_docx:
                plan_data = _ensure_step_fields(fast_docx)
        elif is_file_creation_query:
            filename = "notes.txt"
            if "music" in lower_goal:
                filename = "music_theory_notes.txt"
            elif "todo" in lower_goal:
                filename = "todo.txt"
            else:
                for word in goal.split():
                    clean_w = word.strip("\",';:")
                    if any(clean_w.endswith(ext) for ext in (".txt", ".md", ".py", ".json", ".csv")):
                        filename = clean_w
                        break

            target_path = f"~/Desktop/{filename}" if "desktop" in lower_goal else filename

            content = ""
            if has_api_key:
                try:
                    msg = await ainvoke_with_dynamic_switch(
                        [
                            SystemMessage(content="You are a file content generator. Output ONLY the raw text notes requested by the user, with no commentary, no markdown codeblocks, and no extra text."),
                            HumanMessage(content=f"Generate the text content for: {goal}")
                        ],
                        operation="fast",
                        temperature=0.3
                    )
                    content = msg.content.strip()
                except Exception:
                    pass

            if not content:
                content = (
                    "Music Theory Notes:\n"
                    "- Scales: Major (W-W-H-W-W-W-H), Natural Minor (W-H-W-W-H-W-W)\n"
                    "- Triads: Major (1-3-5), Minor (1-b3-5), Diminished (1-b3-b5), Augmented (1-3-#5)\n"
                    "- Seventh Chords: Major 7th (1-3-5-7), Dominant 7th (1-3-5-b7), Minor 7th (1-b3-5-b7)\n"
                    "- Circle of Fifths: C, G, D, A, E, B, F#, C#, Ab, Eb, Bb, F\n"
                ) if "music" in lower_goal else f"Notes generated by NEXUS for: {goal}\n"

            plan_data = [{
                "title": f"Create {filename}",
                "description": f"Write text file to {target_path}",
                "tool": "write_file",
                "args": {
                    "path": target_path,
                    "content": content
                }
            }]
        elif (
            any(w in lower_goal for w in ("search for", "web search", "lookup", "find news")) or
            lower_goal.startswith("search ") or
            (lower_goal.startswith("google ") and not any(k in lower_goal for k in ("form", "doc", "sheet", "drive", "meet", "chrome")))
        ):
            query = goal
            for prefix in ("search for", "search", "google for", "google", "lookup", "find news about"):
                if lower_goal.startswith(prefix):
                    query = goal[len(prefix):].strip()
                    break
            plan_data = [{
                "title": f"Web search for '{query}'",
                "description": "Retrieve live information from the web.",
                "tool": "web_search",
                "args": {"query": query}
            }]
        elif intent == "web_automation" or any(w in lower_goal for w in ("inspect dom", "page source", "html source", "browser tab", "browser tabs", "click button", "fill form", "extract elements", "read tab")):
            if any(w in lower_goal for w in ("tab", "tabs")):
                plan_data = [{
                    "title": "Get Browser Tabs",
                    "description": "Discover open browser tabs and active targets.",
                    "tool": "browser_get_tabs",
                    "args": {}
                }]
            elif any(w in lower_goal for w in ("source", "html", "inspect", "element", "dom")):
                plan_data = [{
                    "title": "Inspect Browser DOM",
                    "description": "Inspect active webpage DOM and interactive elements.",
                    "tool": "browser_inspect",
                    "args": {"include_html": "html" in lower_goal or "source" in lower_goal}
                }]
            else:
                plan_data = [
                    {"title": "Inspect Page Elements", "description": "Extract interactive buttons and inputs from active DOM.", "tool": "browser_inspect", "args": {}},
                ]
        elif intent == "shell" or any(w in lower_goal for w in ("chrome", "browser", "incognito", "notepad", "calc", "calculator", "terminal", "powershell", "code", "vscode", "explorer", "open ", "launch ", "start ")):
            cmd = ""
            if "incognito" in lower_goal and "chrome" in lower_goal:
                cmd = "start chrome --incognito"
            elif "chrome" in lower_goal:
                cmd = "start chrome"
            elif "edge" in lower_goal:
                cmd = "start msedge -inprivate" if ("inprivate" in lower_goal or "incognito" in lower_goal) else "start msedge"
            elif "notepad" in lower_goal:
                cmd = "start notepad"
            elif "calc" in lower_goal:
                cmd = "start calc"
            elif "code" in lower_goal or "vscode" in lower_goal:
                cmd = "start code ."
            elif "terminal" in lower_goal or "powershell" in lower_goal:
                cmd = "start powershell"
            elif "explorer" in lower_goal or "folder" in lower_goal:
                cmd = "explorer ."
            elif lower_goal.startswith("start ") or lower_goal.startswith("open "):
                cmd = lower_goal.replace("open ", "start ", 1)
            else:
                cmd = goal

            plan_data = [{
                "title": f"Execute '{cmd}'",
                "description": f"Execute system shell command on host OS.",
                "tool": "run_command",
                "args": {"command": cmd}
            }]
        elif intent == "file_op" and any(w in lower_goal for w in ("list", "ls", "dir", "files")):
            plan_data = [{
                "title": "List directory contents",
                "description": "List files in the current workspace.",
                "tool": "list_directory",
                "args": {"path": "."}
            }]
        elif intent == "file_op" and any(w in lower_goal for w in ("search", "find", "grep")):
            query = goal.split()[-1] if goal.split() else ""
            plan_data = [{
                "title": f"Search files for '{query}'",
                "description": "Search files in the current workspace.",
                "tool": "search_files",
                "args": {"query": query}
            }]
        else:
            if has_api_key:
                try:
                    ans_msg = await ainvoke_with_dynamic_switch(
                        [
                            SystemMessage(content="You are NEXUS, an intelligent and helpful AI assistant. Answer the user's inquiry clearly, thoroughly, and accurately in markdown format."),
                            HumanMessage(content=goal or state.get("user_input", ""))
                        ],
                        operation="fast",
                        temperature=0.3
                    )
                    answer = ans_msg.content.strip() if ans_msg and ans_msg.content else _get_fallback_answer(goal)
                except Exception:
                    answer = _get_fallback_answer(goal)
            else:
                answer = _get_fallback_answer(goal)

            plan_data = [{
                "title": "NEXUS Assistant",
                "description": "Respond to user inquiry.",
                "tool": "ai_response",
                "args": {"answer": answer}
            }]

    steps: list[PlanStep] = _ensure_step_fields(plan_data or [])  # type: ignore[assignment]

    active_model = "google/gemma-4-26b-a4b-it" if get_gemma_api_key() else "qwen/qwen3.8-27b"
    try:
        from backend.agent.router.model_router import model_pool
        active_model = model_pool.get_active_reasoning_model()
    except Exception:
        pass

    obs = state.get("observations", []).copy()
    obs.append(f"Formulated plan with {len(steps)} step(s).")

    cur_llm_calls = state.get("llm_calls_count", 0) + (1 if has_api_key else 0)
    return {
        "plan": steps,
        "current_step": 0,
        "observations": obs,
        "execution_status": "executing",
        "selected_model": active_model,
        "llm_calls_count": cur_llm_calls,
    }
