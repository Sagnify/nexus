"""Intent classification node for NEXUS."""
from __future__ import annotations
import json
from langchain_core.messages import SystemMessage, HumanMessage
from backend.agent.state import NexusState
from backend.agent.router.model_router import ainvoke_with_dynamic_switch
from backend.core.config import get_groq_api_key, get_gemma_api_key

INTENT_PROMPT = """You are the NEXUS Intent Classifier.
Classify the user input into ONE of these intent categories:
- "web_automation": Interacting with open websites/web pages, filling web forms, clicking webpage controls/buttons, inspecting DOM/HTML, navigating browser tabs, executing browser console scripts, scraping live open tabs.
- "coding": Writing, fixing, refactoring, or analyzing code.
- "file_op": Reading, creating, editing, deleting, or listing files, or generating Word/DOCX documents, Excel/XLSX spreadsheets, and PowerPoint/PPTX presentations.
- "shell": Running system terminal commands, installing packages, checking processes, launching desktop applications, windows, or general system utilities (e.g. Notepad, Calculator, VS Code, Terminal).
- "research": Searching live internet/Google, summarizing, deep web/filesystem exploration.
- "question": Explaining a concept, Q&A, advice, general query that does not require system modifications.
- "general": Conversational or ambiguous input.

Also extract a concise, concrete 1-sentence goal.

Respond strictly with a JSON object:
{"intent": "<category>", "goal": "<concise goal>"}
"""


async def intent_node(state: NexusState) -> dict:
    user_input = state.get("user_input", "").strip()
    active_target = state.get("active_target") or {}
    target_type = str(active_target.get("target_type") or "").lower()
    target_app = str(active_target.get("application") or "").lower()
    lower_input = user_input.lower()

    # 0. Check Deterministic Fast-Path Router (Zero LLM Calls, <1ms)
    try:
        from backend.agent.router.fastpath_router import match_fastpath_plan
        fast_res = match_fastpath_plan(user_input, active_target=active_target)
        if fast_res:
            return {
                "intent": fast_res.intent,
                "goal": fast_res.goal,
                "plan": fast_res.plan,
                "fast_path_used": fast_res.category,
                "tokens_saved_estimate": fast_res.tokens_saved,
                "llm_calls_count": 0,
                "deterministic_actions_count": len(fast_res.plan),
                "execution_status": "planning",
                "selected_model": "fastpath-deterministic",
            }
    except Exception as e:
        pass

    # 0.1 Check Normalized Plan Cache (Zero LLM Calls, Parameterized Templates)
    try:
        from backend.agent.router.plan_cache import get_cached_plan
        cached_plan = get_cached_plan(user_input)
        if cached_plan:
            return {
                "intent": "file_op",
                "goal": user_input,
                "plan": cached_plan,
                "cache_hit": True,
                "tokens_saved_estimate": 3200,
                "llm_calls_count": 0,
                "deterministic_actions_count": len(cached_plan),
                "execution_status": "planning",
                "selected_model": "cached-plan",
            }
    except Exception as e:
        pass

    # 0.2 Instant Direct Knowledge / Question Fast-Path (<0.1ms, Zero LLM Calls)
    question_starters = (
        "who is ", "who was ", "who are ", "who were ", "who created ", "who built ", "who founded ", "who won ",
        "what is ", "what was ", "what are ", "what were ", "what does ", "what do ", "what did ", "what causes ",
        "where is ", "where was ", "where are ", "where were ", "where does ",
        "when is ", "when was ", "when did ", "when will ",
        "why is ", "why was ", "why are ", "why do ", "why does ", "why did ",
        "how does ", "how do ", "how did ", "how is ", "how was ", "how to ", "how can ",
        "which is ", "which was ", "which are ",
        "tell me about ", "tell me a fact", "explain ", "describe ", "define ", "summarize ",
        "give me a brief ", "give me an overview", "history of ", "biography of ",
    )
    is_q = any(lower_input.startswith(prefix) for prefix in question_starters) or (lower_input.endswith("?") and len(lower_input.split()) >= 2)
    is_action_cmd = any(lower_input.startswith(p) for p in ("open ", "launch ", "start ", "run ", "calc ", "calculate ", "schedule ", "remind ", "take screenshot")) or any(w in lower_input for w in ("create file", "write file", "save file", "delete file", "search google", "search youtube"))
    if is_q and not is_action_cmd:
        return {
            "intent": "question",
            "goal": user_input,
            "execution_status": "thinking",
            "selected_model": "direct-knowledge-fastpath",
            "llm_calls_count": 0,
        }


    # Active Target Fast-Path (Word & Excel & Document Formatting)
    if target_type in ("word", "excel") or ("word" in target_app and target_type != "auto") or ("excel" in target_app and target_type != "auto"):
        doc_terms = ("page border", "border", "heading", "font size", "paragraph", "table", "style", "cell", "sheet")
        if any(w in lower_input for w in doc_terms):
            if not any(p in lower_input for p in ("on google", "on youtube", "on reddit", "search google", "open browser")):
                return {
                    "intent": "file_op",
                    "goal": user_input,
                    "execution_status": "thinking",
                    "selected_model": "active-target-fastpath",
                }

    # Instant fast-path for media playback & controls (Spotify Desktop, Web, VLC, etc.)
    try:
        from backend.agent.router.media_fastpath import extract_media_intent
        media_intent = extract_media_intent(user_input)
        if media_intent:
            intent_type = "web_automation" if (media_intent.get("service") in ("youtube", "youtube_music", "soundcloud") or not media_intent.get("prefer_desktop", True)) else "shell"
            return {
                "intent": intent_type,
                "goal": user_input,
                "execution_status": "thinking",
                "selected_model": "media-fastpath",
            }
    except Exception:
        pass

    # Instant fast-path for search queries (Google, YouTube, Reddit, etc.)
    try:
        from backend.agent.router.search_fastpath import extract_search_intent
        if extract_search_intent(user_input, active_target=active_target):
            return {
                "intent": "web_automation",
                "goal": user_input,
                "execution_status": "thinking",
                "selected_model": "search-fastpath",
            }
    except Exception:
        pass

    # Instant fast-path for presentation & PowerPoint creation
    if any(w in lower_input for w in ("powerpoint", "power point", "presentation", "slides", "ppt", "pptx", "slide deck")):
        if any(w in lower_input for w in ("make", "create", "write", "save", "generate", "build", "export", "deck", "slides", "topic", "for", "on", "about")):
            return {
                "intent": "file_op",
                "goal": user_input,
                "execution_status": "thinking",
                "selected_model": "presentation-fastpath",
            }

    has_api_key = bool(get_groq_api_key() or get_gemma_api_key())

    if not has_api_key:
        # Heuristic fallback if API key isn't configured yet
        lower = user_input.lower()
        if any(w in lower for w in ("click button", "fill form", "inspect dom", "browser tab", "web page", "page source", "html source", "scrape tab", "browser_")):
            intent = "web_automation"
        elif any(w in lower for w in ("run", "exec", "npm", "pip", "bash", "powershell", "git", "open", "launch", "start", "chrome", "edge", "browser")):
            intent = "shell"
        elif any(w in lower for w in ("file", "read", "write", "create file", "delete", "list", "docx", "word doc", "report in word", "document.", "xlsx", "excel", "spreadsheet", "csv", "powerpoint", "power point", "presentation", "slides", "ppt", "pptx")):
            intent = "file_op"
        elif any(w in lower for w in ("code", "function", "fix", "bug", "component", "ts", "python")):
            intent = "coding"
        elif any(w in lower for w in ("what", "why", "how", "explain", "who")):
            intent = "question"
        else:
            intent = "general"




        return {
            "intent": intent,
            "goal": user_input,
            "execution_status": "thinking",
            "selected_model": "heuristic-fallback",
        }

    active_model = "google/gemma-4-26b-a4b-it" if get_gemma_api_key() else "qwen/qwen3.8-27b"
    try:
        from backend.agent.router.model_router import model_pool
        active_model = model_pool.get_active_reasoning_model()
    except Exception:
        pass

    try:
        messages = [
            SystemMessage(content=INTENT_PROMPT),
            HumanMessage(content=user_input)
        ]
        response = await ainvoke_with_dynamic_switch(messages, operation="fast", temperature=0.0)
        content = response.content.strip()

        # Parse json
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            data = json.loads(content[start:end])
            return {
                "intent": data.get("intent", "general"),
                "goal": data.get("goal", user_input),
                "execution_status": "thinking",
                "selected_model": active_model,
                "llm_calls_count": state.get("llm_calls_count", 0) + 1,
            }
    except Exception:
        pass

    lower = user_input.lower()
    if any(w in lower for w in ("click", "fill", "form", "inspect", "tab", "web", "browser", "html", "url", "page")):
        detected_intent = "web_automation"
    elif any(w in lower for w in ("run", "exec", "npm", "pip", "bash", "powershell", "cmd", "launch", "open", "start")):
        detected_intent = "shell"
    else:
        detected_intent = "general"

    return {
        "intent": detected_intent,
        "goal": user_input,
        "execution_status": "thinking",
        "selected_model": active_model,
    }
