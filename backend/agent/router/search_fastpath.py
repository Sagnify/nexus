"""Search Fastpath Compiler for instant (<1ms) web searches."""
from __future__ import annotations
import re
import urllib.parse

SEARCH_PROVIDERS = {
    "google": {
        "name": "Google",
        "url_template": "https://www.google.com/search?q={query}",
    },
    "youtube": {
        "name": "YouTube",
        "url_template": "https://www.youtube.com/results?search_query={query}",
    },
    "reddit": {
        "name": "Reddit",
        "url_template": "https://www.reddit.com/search/?q={query}",
    },
    "github": {
        "name": "GitHub",
        "url_template": "https://github.com/search?q={query}",
    },
    "wikipedia": {
        "name": "Wikipedia",
        "url_template": "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    },
    "amazon": {
        "name": "Amazon",
        "url_template": "https://www.amazon.com/s?k={query}",
    },
    "twitter": {
        "name": "X / Twitter",
        "url_template": "https://x.com/search?q={query}",
    },
    "x": {
        "name": "X",
        "url_template": "https://x.com/search?q={query}",
    },
    "bing": {
        "name": "Bing",
        "url_template": "https://www.bing.com/search?q={query}",
    },
    "spotify": {
        "name": "Spotify",
        "url_template": "https://open.spotify.com/search/{query}",
    },
}


def extract_search_intent(goal: str, active_target: Optional[dict] = None) -> tuple[str, str, bool] | None:
    """
    Extracts (provider_key, clean_query, click_first) from user search goal, or None.
    """
    if not goal:
        return None

    lower = goal.lower().strip()

    # Guard: Never hijack document, spreadsheet, formatting or active Word/Excel target commands
    doc_keywords = ("word", "docx", "excel", "xlsx", "page border", "border", "heading", "font", "paragraph", "cell", "sheet")
    target_type = str(active_target.get("target_type") if active_target else "").lower()
    target_app = str(active_target.get("application") if active_target else "").lower()

    if target_type in ("word", "excel") or "word" in target_app or "excel" in target_app or any(w in lower for w in doc_keywords):
        # Unless user explicitly asked to search Google/YouTube/Reddit
        if not any(p in lower for p in ("on google", "on youtube", "on reddit", "on github", "search google", "google for")):
            return None

    # Strip conversational prefixes and punctuation
    lower = re.sub(r'^(?:(?:hey|hi|hello|ok|okay)\s+)?(?:nexus[\s,:-]*)+', '', lower).strip()
    lower = re.sub(r'^(?:please\s+|can\s+you\s+|could\s+you\s+)+', '', lower).strip()
    lower = re.sub(r'^[\s,:-]+', '', lower).strip()

    # Check if user specifically requested playing / clicking the first result
    click_first = bool(re.search(r'\b(?:and\s+)?(?:play|click|watch|open)\s+(?:the\s+)?(?:first|top|1st)\s+(?:video|result|link|song)\b', lower))
    # Strip that clause from the search query
    lower = re.sub(r'\s+(?:and\s+)?(?:play|click|watch|open)\s+(?:the\s+)?(?:first|top|1st)\s+(?:video|result|link|song)\b.*$', '', lower).strip()

    providers_pattern = r'(?:google|youtube|reddit|github|wikipedia|amazon|twitter|x|bing|spotify)'

    # 1. Pattern: "open <provider> and search (for) <query>" / "go to <provider> and search (for) <query>"
    m = re.search(rf'^(?:open|go\s+to|visit|launch)\s+({providers_pattern})\s+(?:and\s+)?search\s+(?:for\s+)?(.+)', lower)
    if m:
        return m.group(1), m.group(2).strip(), click_first

    # 2. Pattern: "search <provider> for <query>" or "search on/in <provider> for <query>"
    m = re.search(rf'^(?:search|look\s+up|find)\s+(?:(?:on|in)\s+)?({providers_pattern})\s+for\s+(.+)', lower)
    if m:
        return m.group(1), m.group(2).strip(), click_first

    # 3. Pattern: "search (for) <query> on/in <provider>"
    m = re.search(rf'^(?:search|look\s+up|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+({providers_pattern})$', lower)
    if m:
        return m.group(2), m.group(1).strip(), click_first

    # 4. Pattern: "<provider> search (for) <query>"
    m = re.search(rf'^({providers_pattern})\s+(?:search\s+for|search)\s+(.+)', lower)
    if m:
        return m.group(1), m.group(2).strip(), click_first

    # 5. Pattern: "play <query> on youtube" / "listen to <query> on youtube" / "watch <query> on youtube"
    m = re.search(r'^(?:play|listen\s+to|watch)\s+(.+?)\s+on\s+youtube$', lower)
    if m:
        return "youtube", m.group(1).strip(), True

    # 6. Pattern: Generic search without provider: "search (for) <query>" / "google <query>"
    m = re.search(r'^(?:search\s+for|search|look\s+up|google)\s+(.+)', lower)
    if m:
        q = m.group(1).strip()
        # Avoid hijacking local file / system searches
        if any(w in q for w in ("file", "folder", "desktop", "directory", "local", "pc", "computer", "disk")):
            return None
        # Avoid hijacking web application actions, forms, documents, or automations (which belong to learned skills or agents)
        app_action_words = (
            "form", "forms", "survey", "gform", "doc", "docs", "sheet", "sheets",
            "slide", "slides", "drive", "mail", "gmail", "calendar", "keep", "meet",
            "create", "make", "build", "fill", "automate", "workflow", "recipe", "skill"
        )
        first_word = q.split()[0] if q.split() else ""
        if any(first_word == w or q.startswith(w + " ") for w in app_action_words):
            return None
        return "google", q, click_first

    return None


def build_search_plan(goal: str) -> list[dict] | None:
    """
    Deterministic <1ms plan compiler for search queries.
    Directly navigates to the platform's search results page.
    """
    match = extract_search_intent(goal)
    if not match:
        return None

    provider, query, click_first = match
    # Clean query from trailing punctuation
    query = re.sub(r'[\s.!?]+$', '', query).strip()
    if not query:
        return None

    provider_info = SEARCH_PROVIDERS.get(provider, SEARCH_PROVIDERS["google"])
    encoded_query = urllib.parse.quote_plus(query)
    target_url = provider_info["url_template"].format(query=encoded_query)

    plan = [
        {
            "title": f"Search {provider_info['name']} for '{query}'",
            "description": f"Navigate directly to {provider_info['name']} search results for '{query}'",
            "tool": "browser_navigate",
            "args": {"url": target_url}
        }
    ]

    if click_first and provider == "youtube":
        plan.extend([
            {
                "title": "Wait for Video Results",
                "description": "Allow YouTube search results to load",
                "tool": "browser_wait",
                "args": {"timeout_seconds": 1.5}
            },
            {
                "title": "Play First Video",
                "description": f"Click the top video result for '{query}'",
                "tool": "browser_click",
                "args": {
                    "selector": "ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title, #contents ytd-video-renderer a#thumbnail",
                    "text": "Play"
                }
            }
        ])

    return plan
