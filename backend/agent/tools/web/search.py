"""Live Web Search tool for NEXUS with multi-engine resilience."""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import re
import urllib.parse
from bs4 import BeautifulSoup
import httpx

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
}


def _clean_text(text: str) -> str:
    """Normalize whitespace and strip zero-width or non-breaking characters."""
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def _clean_url(raw_url: str) -> str:
    """Unwrap search engine redirect URLs (DuckDuckGo, Bing) to get direct destination URLs."""
    if not raw_url:
        return ""
    raw_url = raw_url.strip()
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    elif raw_url.startswith("/"):
        raw_url = "https://duckduckgo.com" + raw_url

    parsed = urllib.parse.urlparse(raw_url)

    # DuckDuckGo redirect unwrapping
    if "duckduckgo.com" in parsed.netloc and "/l/" in parsed.path:
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return urllib.parse.unquote(qs["uddg"][0])

    # Bing redirect unwrapping (base64 encoded u=a1...)
    if "bing.com" in parsed.netloc and "/ck/a" in parsed.path:
        qs = urllib.parse.parse_qs(parsed.query)
        u = qs.get("u", [""])[0]
        if u.startswith("a1"):
            b64_str = u[2:]
            pad = len(b64_str) % 4
            if pad:
                b64_str += "=" * (4 - pad)
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass

    return raw_url


class WebSearchTool(NexusTool):
    name = "web_search"
    description = "Search the live web for up-to-date information, news, documentation, or facts."
    risk_level = RiskLevel.SAFE

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query keywords",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 5)",
                    },
                },
                "required": ["query"],
            },
        }

    async def execute(self, query: str = "", max_results: int = 5, **kwargs) -> ToolResult:
        # Coerce query from common parameter aliases if needed
        if not query:
            query = kwargs.get("q") or kwargs.get("search_query") or kwargs.get("keywords") or ""

        if not str(query).strip():
            return ToolResult(success=False, output="", error="Search query cannot be empty.")

        query_clean = str(query).strip()

        # Coerce max_results safely
        try:
            max_results = int(max_results)
        except (ValueError, TypeError):
            max_results = 5
        max_results = max(1, min(max_results, 20))

        results: list[dict] = []
        seen_urls: set[str] = set()

        def add_result(title: str, url: str, snippet: str) -> None:
            title_c = _clean_text(title)
            url_c = _clean_url(url)
            snippet_c = _clean_text(snippet)
            if not title_c or not url_c:
                return
            norm_url = url_c.lower().rstrip("/")
            if norm_url in seen_urls:
                return
            seen_urls.add(norm_url)
            results.append({
                "title": title_c,
                "url": url_c,
                "snippet": snippet_c,
            })

        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=8.0,
        ) as client:
            # 1. DuckDuckGo HTML Search
            try:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query_clean},
                )
                if resp.status_code == 200 and "Unfortunately, bots use DuckDuckGo too" not in resp.text:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for b in soup.select(".result__body"):
                        t_el = b.select_one(".result__title a")
                        s_el = b.select_one(".result__snippet")
                        if t_el:
                            add_result(
                                title=t_el.get_text(),
                                url=t_el.get("href", ""),
                                snippet=s_el.get_text() if s_el else "",
                            )
                            if len(results) >= max_results:
                                break
            except Exception as e:
                logger.debug("DDG HTML search failed: %s", e)

            # 2. Bing Search (High reliability fallback when DDG challenges/rate-limits)
            if len(results) < max_results:
                try:
                    resp = await client.get(
                        "https://www.bing.com/search",
                        params={"q": query_clean},
                    )
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for algo in soup.select("li.b_algo"):
                            a = algo.select_one("h2 a")
                            if not a:
                                continue
                            p = algo.select_one(".b_caption p") or algo.select_one("p")
                            add_result(
                                title=a.get_text(),
                                url=a.get("href", ""),
                                snippet=p.get_text() if p else "",
                            )
                            if len(results) >= max_results:
                                break
                except Exception as e:
                    logger.debug("Bing search fallback failed: %s", e)

            # 3. DuckDuckGo Lite (if HTML & Bing had low results)
            if len(results) < max_results:
                try:
                    resp = await client.post(
                        "https://lite.duckduckgo.com/lite/",
                        data={"q": query_clean},
                    )
                    if resp.status_code == 200 and "Unfortunately, bots use DuckDuckGo too" not in resp.text:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for link in soup.select(".result-link"):
                            title = link.get_text()
                            href = link.get("href", "")
                            # Find snippet in the corresponding sibling row
                            snippet = ""
                            parent_tr = link.find_parent("tr")
                            if parent_tr:
                                next_tr = parent_tr.find_next_sibling("tr")
                                if next_tr:
                                    s_el = next_tr.select_one(".result-snippet")
                                    if s_el:
                                        snippet = s_el.get_text()
                            add_result(title=title, url=href, snippet=snippet)
                            if len(results) >= max_results:
                                break
                except Exception as e:
                    logger.debug("DDG Lite search failed: %s", e)

            # 4. Brave Search Fallback
            if len(results) < max_results:
                try:
                    resp = await client.get(
                        "https://search.brave.com/search",
                        params={"q": query_clean},
                    )
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for card in soup.select("div.snippet"):
                            t_el = card.select_one("div.title")
                            a_el = card.select_one("a[href]")
                            if not t_el or not a_el:
                                continue
                            s_el = (
                                card.select_one(".generic-snippet")
                                or card.select_one(".snippet-description")
                                or card.select_one(".content")
                                or card.select_one("p")
                            )
                            add_result(
                                title=t_el.get_text(),
                                url=a_el.get("href", ""),
                                snippet=s_el.get_text() if s_el else "",
                            )
                            if len(results) >= max_results:
                                break
                except Exception as e:
                    logger.debug("Brave search fallback failed: %s", e)

            # 5. Wikipedia & DDG Instant Answer Fallback (Encyclopedic / Topical)
            if not results:
                # Try DuckDuckGo Instant Answer
                try:
                    encoded_q = urllib.parse.quote_plus(query_clean)
                    api_url = f"https://api.duckduckgo.com/?q={encoded_q}&format=json&no_html=1&skip_disambig=1"
                    resp = await client.get(api_url, timeout=5.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        abstract = data.get("AbstractText")
                        abstract_url = data.get("AbstractURL")
                        if abstract:
                            add_result(
                                title=data.get("Heading", query_clean),
                                url=abstract_url or "https://duckduckgo.com",
                                snippet=abstract,
                            )
                        for topic in data.get("RelatedTopics", []):
                            if isinstance(topic, dict) and topic.get("Text"):
                                add_result(
                                    title=topic.get("Text")[:60] + "...",
                                    url=topic.get("FirstURL", ""),
                                    snippet=topic.get("Text"),
                                )
                                if len(results) >= max_results:
                                    break
                except Exception as e:
                    logger.debug("DDG Instant Answer fallback failed: %s", e)

                # Try Wikipedia Search API
                if not results:
                    try:
                        resp = await client.get(
                            "https://en.wikipedia.org/w/api.php",
                            params={
                                "action": "query",
                                "list": "search",
                                "srsearch": query_clean,
                                "format": "json",
                                "utf8": 1,
                                "srlimit": max_results,
                            },
                            headers={"User-Agent": "NexusSearchBot/1.0"},
                            timeout=5.0,
                        )
                        if resp.status_code == 200:
                            wiki_data = resp.json()
                            for item in wiki_data.get("query", {}).get("search", []):
                                w_title = item.get("title", "")
                                w_snippet_raw = item.get("snippet", "")
                                w_snippet = BeautifulSoup(w_snippet_raw, "html.parser").get_text()
                                w_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(w_title.replace(' ', '_'))}"
                                add_result(title=w_title, url=w_url, snippet=w_snippet)
                                if len(results) >= max_results:
                                    break
                    except Exception as e:
                        logger.debug("Wikipedia search fallback failed: %s", e)

        if not results:
            return ToolResult(
                success=True,
                output=f"No web results found for '{query_clean}'.",
                metadata={"results": [], "query": query_clean, "count": 0},
            )

        # Format output as clean markdown list
        final_results = results[:max_results]
        formatted_lines = [f"### Web Search Results for '{query_clean}':\n"]
        for idx, r in enumerate(final_results, 1):
            formatted_lines.append(f"{idx}. **[{r['title']}]({r['url']})**")
            if r.get("snippet"):
                formatted_lines.append(f"   {r['snippet']}\n")
            else:
                formatted_lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(formatted_lines).strip(),
            metadata={
                "results": final_results,
                "query": query_clean,
                "count": len(final_results),
            },
        )
