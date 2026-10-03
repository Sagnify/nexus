"""
Speech synthesis and conversational voice response formatting for NEXUS.
Generates concise, human-like voice messages (e.g., "I have successfully created the Excel file on your desktop.")
instead of reading out full technical AI markdown outputs, tables, code blocks, or raw error logs.
"""
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any


def clean_spoken_error(error: Optional[str]) -> str:
    """Transform technical error messages into a short, friendly explanation."""
    if not error:
        return "an unexpected issue occurred"

    err = error.strip()

    # Common pattern checks
    err_lower = err.lower()
    if "live dom" in err_lower or "dom verification" in err_lower or "missing required" in err_lower:
        return "some required items were missing on the page"
    if "iteration limit" in err_lower or "reached iteration" in err_lower:
        return "the task reached the maximum step limit"
    if "not found" in err_lower or "cannot locate" in err_lower or "could not locate" in err_lower:
        return "a required element could not be found on the screen"
    if "timed out" in err_lower or "timeout" in err_lower:
        return "the page or operation timed out"
    if "permission" in err_lower or "denied" in err_lower:
        return "permission was not granted"
    if "rate limit" in err_lower:
        return "the service is temporarily rate limited"
    if "disconnected" in err_lower or "offline" in err_lower:
        return "the browser connection was interrupted"

    # Strip markdown, file paths, brackets, codes
    err = re.sub(r'```.*?```', '', err, flags=re.DOTALL)
    err = re.sub(r'`[^`]+`', '', err)
    err = re.sub(r'\[.*?\]\(.*?\)', '', err)
    err = re.sub(r'[A-Za-z]:\\[\w\s\\/.\-_]+', 'file', err)
    err = re.sub(r'https?://\S+', '', err)
    err = re.sub(r'[#*_~|]', '', err)
    err = re.sub(r'\s+', ' ', err).strip()

    # Extract first sentence or clip to 70 chars
    sentences = re.split(r'[.!?]\s+', err)
    first_sentence = sentences[0].strip() if sentences else err
    if len(first_sentence) > 75:
        first_sentence = first_sentence[:70].rsplit(' ', 1)[0]

    return first_sentence.lower() or "an issue occurred"


def clean_spoken_text(text: Optional[str], max_chars: int = 150) -> str:
    """
    Extract a concise, single-sentence conversational statement from raw markdown or AI output.
    Strips tables, headings, code, bullets, links, and bold formatting.
    """
    if not text:
        return ""

    t = text.strip()

    # 1. Remove code blocks entirely
    t = re.sub(r'```[\s\S]*?```', '', t)

    # 2. Remove table rows completely (any line with pipes |)
    lines = []
    for line in t.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        # Drop markdown tables, dividers, and headers like | Name | Type |
        if line_s.startswith('|') or line_s.endswith('|') or re.match(r'^[-:| ]+$', line_s):
            continue
        # Drop markdown header lines (### Task Completed, etc.)
        if re.match(r'^#{1,6}\s+', line_s):
            clean_hdr = re.sub(r'^#{1,6}\s+', '', line_s).strip()
            # If the header is just a generic label, drop it
            if any(h in clean_hdr.lower() for h in ("task completed", "completed successfully", "execution complete", "steps summary", "task failed", "response", "findings")):
                continue
            lines.append(clean_hdr)
            continue
        lines.append(line_s)

    t = " ".join(lines)

    # 3. Strip inline code `code`
    t = re.sub(r'`([^`]+)`', r'\1', t)

    # 4. Strip links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', t)

    # 5. Strip URLs
    t = re.sub(r'https?://\S+', '', t)

    # 6. Strip bullet symbols and numbering
    t = re.sub(r'(?:^|\s)[-*+]\s+', ' ', t)
    t = re.sub(r'(?:^|\s)\d+\.\s+', ' ', t)

    # 7. Strip bold / italics
    t = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)
    t = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', t)

    # 8. Strip verification badges, emojis, and symbols
    t = re.sub(r'[✅❌⛔⚠️👉💡🔍📌🎉✨]|DOM Verification: Passed', '', t)

    # 9. Clean excessive spaces and punctuation
    t = re.sub(r'\s+', ' ', t).strip()

    if not t:
        return ""

    # 10. Extract first 1-2 clean complete sentences
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', t) if s.strip()]
    if sentences:
        candidate = sentences[0]
        # If first sentence is very brief (e.g. "Sure!", "Done."), append the next sentence
        if len(candidate) < 35 and len(sentences) > 1:
            candidate = f"{candidate} {sentences[1]}"
        # Ensure sentence ends with punctuation
        if not candidate.endswith(('.', '!', '?')):
            candidate += '.'
        return candidate

    return t if t.endswith(('.', '!', '?')) else f"{t}."


def generate_spoken_message(
    goal: str = "",
    user_input: str = "",
    plan: Optional[List[Dict[str, Any]]] = None,
    execution_status: str = "completed",
    error: Optional[str] = None,
    final_response: Optional[str] = None,
) -> str:
    """
    Generate a short, natural human-like spoken message for voice output.
    Speaks clean messages like "I have successfully created the Excel file on your desktop."
    """
    plan = plan or []
    full_context = f"{goal} {user_input}".lower()

    # Collect tool names used in the plan
    tools_used = [str(s.get("tool", "")).lower() for s in plan]
    all_tools_str = " ".join(tools_used)

    is_failed = execution_status in ("failed", "cancelled") or (bool(error) and not final_response)

    # Check for specific intents
    is_excel = (
        any(k in full_context for k in ("excel", "spreadsheet", ".xlsx", "csv", "sheet"))
        or any("spreadsheet" in t or "excel" in t for t in tools_used)
    )
    is_word = (
        any(k in full_context for k in ("word document", "doc", ".docx", "create document"))
        or any("document" in t for t in tools_used)
    )
    is_file = (
        any(k in full_context for k in ("create file", "write file", "save file", "script", "desktop file"))
        or "write_file" in tools_used
    )
    is_email = (
        any(k in full_context for k in ("send email", "send mail", "compose email", "compose mail", "dispatch email"))
    )
    is_form = (
        any(k in full_context for k in ("google form", "create form", "build form", "fill form", "submit form"))
    )
    is_app_open = (
        any(k in full_context for k in (
            "open chrome", "open edge", "open app", "launch", "open application",
            "open calculator", "launch calculator", "open calc", "launch calc",
            "open notepad", "launch notepad", "open spotify", "open vs code", "open vscode", "open code",
            "open terminal", "open powershell", "open paint", "open word", "open excel"
        ))
        or any(k in full_context for k in ("open ", "launch ", "start ", "bring up "))
    ) and any(t in ("run_command", "activate_window") for t in tools_used)
    is_deep_research = (
        any("deep_research" in t for t in tools_used)
        or any(k in full_context for k in ("deep research", "research on", "research about"))
    )

    # 1. Handle Failures
    if is_failed:
        short_err = clean_spoken_error(error)
        if is_deep_research:
            return f"I couldn't complete the research because {short_err}."
        if is_excel:
            return f"I couldn't create the Excel file because {short_err}."
        if is_word:
            return f"I couldn't create the document because {short_err}."
        if is_email:
            return f"I couldn't send the email because {short_err}."
        if is_form:
            return f"I couldn't complete the form because {short_err}."
        if is_file:
            return f"I couldn't save the file because {short_err}."
        return f"I couldn't complete the task: {short_err}."

    # 2. Handle Completions for Known High-Value Actions
    if is_deep_research:
        if final_response and ("> [!NOTE]" in final_response or "proprietary" in final_response.lower() or "cannot programmatically generate" in final_response.lower()):
            for ext in ("cpr", "psd", "ps", "ptx", "flp", "aep", "prproj", "dwg", "blend", "max"):
                if ext in full_context.lower() or (final_response and f".{ext}" in final_response.lower()):
                    return f"I have completed the deep research and saved the report to your desktop. Note that proprietary {ext.upper()} project files cannot be created natively without host software, so I compiled the full documented report instead."
        if any(k in full_context for k in ("excel", "xlsx", "spreadsheet", "sheet")):
            return "I have completed the deep research and saved the data spreadsheet with citations to your desktop."
        elif any(k in full_context for k in ("csv",)):
            return "I have completed the deep research and saved the CSV data matrix to your desktop."
        elif any(k in full_context for k in ("pdf",)):
            return "I have completed the deep research and saved the PDF report with citations to your desktop."
        return "I have completed the deep research and saved the report with citations to your desktop."

    if is_excel:
        if any(k in full_context for k in ("update", "modify", "format", "add to")):
            return "I have updated the Excel file on your desktop."
        return "I have successfully created the Excel file on your desktop."

    if is_word:
        if any(k in full_context for k in ("update", "modify", "add to")):
            return "I have updated the document on your desktop."
        return "I have successfully created the document on your desktop."

    if is_email:
        return "I have sent the email for you."

    if is_form:
        if "submit" in full_context or "fill" in full_context:
            return "I have filled and submitted the form for you."
        return "I have successfully created the form for you."

    if is_file:
        return "I have successfully saved the file to your desktop."

    if is_app_open:
        for app in ("calculator", "calc", "notepad", "chrome", "edge", "spotify", "vs code", "vscode", "terminal", "powershell", "paint", "word", "excel"):
            if app in full_context:
                display_name = "VS Code" if app in ("vs code", "vscode", "code") else ("Calculator" if app in ("calc", "calculator") else app.capitalize())
                return f"I have opened {display_name} for you."
        return "I have opened the application for you."

    # 3. Conversational / Q&A / Search Tasks: Extract clean sentence from response
    if final_response:
        cleaned_sentence = clean_spoken_text(final_response)
        # Verify it's not a generic header or empty
        if cleaned_sentence and len(cleaned_sentence) > 10:
            cleaned_lower = cleaned_sentence.lower()
            if not any(cleaned_lower.startswith(prefix) for prefix in (
                "task completed", "execution complete", "here are the results", "###"
            )):
                return cleaned_sentence

    # 4. Fallback Default
    return "I have completed your task successfully."


async def generate_spoken_brief(
    goal: str = "",
    user_input: str = "",
    plan: Optional[List[Dict[str, Any]]] = None,
    execution_status: str = "completed",
    error: Optional[str] = None,
    final_response: Optional[str] = None,
) -> str:
    """
    Generate an internal brief specifically crafted for voice speech output.
    This brief is spoken only and kept separate from the rich UI response.
    Never chops sentences, never speaks markdown, and maintains a natural conversational flow.
    """
    # 1. If task failed, deterministic clean error message is fast and precise
    if execution_status in ("failed", "cancelled") or (bool(error) and not final_response):
        return generate_spoken_message(
            goal=goal,
            user_input=user_input,
            plan=plan,
            execution_status="failed",
            error=error,
        )

    # 2. If it's a known desktop action tool or deterministic plan, use instant spoken message generation (<0.1ms)
    tools_used = [str(s.get("tool", "")).lower() for s in (plan or [])]
    deterministic_tools = {
        "spreadsheet_create", "spreadsheet_open", "spreadsheet_save", "spreadsheet_verify",
        "spreadsheet_write_range", "spreadsheet_format_range", "spreadsheet_create_table",
        "word_create", "word_open", "write_file", "delete_file", "send_email",
        "document_create", "document_save", "document_verify", "document_add_title",
        "document_add_heading", "document_add_paragraph", "document_add_bullet",
        "run_command", "activate_window", "press_hotkey", "type_text", "press_key", "click_mouse",
        "play_music", "media_control", "get_current_time"
    }
    is_action_task = any(t in deterministic_tools for t in tools_used)
    if is_action_task and (
        all(t in deterministic_tools for t in tools_used)
        or not final_response
        or len(final_response) < 250
        or any(p in (final_response or "").lower() for p in (
            "successfully executed", "launched application", "verified process",
            "created the document", "created the excel", "saved the file", "opened "
        ))
    ):
        return generate_spoken_message(
            goal=goal,
            user_input=user_input,
            plan=plan,
            execution_status=execution_status,
            final_response=final_response,
        )

    # 3. For informational, Q&A, or rich responses: generate a dedicated concise spoken brief using fast LLM
    if final_response and len(final_response.strip()) > 30:
        try:
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch, get_groq_api_key
            from langchain_core.messages import SystemMessage, HumanMessage
            import asyncio

            if get_groq_api_key():
                prompt = (
                    "You are generating a spoken audio brief for a virtual assistant. "
                    "In 1 to 2 natural, complete, conversational sentences, summarize the core answer so the user can hear it naturally. "
                    "Rules:\n"
                    "- Speak in complete sentences without chopping or cutting off.\n"
                    "- Never include markdown symbols (no asterisks, backticks, hashes, or bullet points).\n"
                    "- Never list tables, raw URLs, code blocks, or emojis.\n"
                    "- Be direct, warm, and concise."
                )
                user_msg = f"User asked: {user_input or goal}\n\nFull response:\n{final_response[:1000]}"

                coro = ainvoke_with_dynamic_switch(
                    [SystemMessage(content=prompt), HumanMessage(content=user_msg)],
                    operation="fast",
                    temperature=0.3,
                )
                res = await asyncio.wait_for(coro, timeout=3.0)
                spoken = clean_spoken_text(res.content.strip())
                if spoken and len(spoken) > 10:
                    return spoken
        except Exception:
            pass

    # 4. Fallback to clean deterministic sentence extraction
    return generate_spoken_message(
        goal=goal,
        user_input=user_input,
        plan=plan,
        execution_status=execution_status,
        final_response=final_response,
    )

