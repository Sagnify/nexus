"""Image search and download engine for PowerPoint presentations."""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict
import httpx
from PIL import Image

logger = logging.getLogger("nexus.presentation_images")

CACHE_DIR = Path("scratch") / "images"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "NexusPresentationEngine/1.0 (https://nexus.local; contact@nexus.ai)"


async def _download_and_optimize_image(url: str, filename_prefix: str = "img") -> Optional[Path]:
    """Download image from URL, validate with PIL, resize to presentation resolution, and save."""
    try:
        url_clean = url.split("?")[0] if "utm_source" in url else url
        headers = {"User-Agent": USER_AGENT}

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
            resp = await client.get(url_clean)
            if resp.status_code != 200 or len(resp.content) < 4000:
                logger.debug(f"Failed to fetch image from {url}: status {resp.status_code}")
                return None

            raw_bytes = resp.content

        # Verify and optimize with PIL
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            # Skip unsupported / non-photo formats
            if img.format not in ("JPEG", "PNG", "WEBP", "MPO"):
                return None

            # Skip tiny icons or banners
            w, h = img.size
            if w < 250 or h < 180:
                return None

            # Convert RGBA/P to RGB for clean JPEG saving
            if img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", img.size, (20, 24, 33))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[3])
                else:
                    bg.paste(img.convert("RGBA"))
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Resize to presentation-ready dimensions (max 1280x800) preserving aspect ratio
            img.thumbnail((1280, 800), Image.Resampling.LANCZOS)

            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
            safe_prefix = re.sub(r"[^\w-]", "", filename_prefix)[:20]
            out_path = CACHE_DIR / f"{safe_prefix}_{url_hash}.jpg"

            img.save(str(out_path), "JPEG", quality=85, optimize=True)
            logger.info(f"Successfully downloaded and cached presentation image: {out_path} ({img.size})")
            return out_path.resolve()

        except Exception as img_err:
            logger.debug(f"PIL verification failed for image {url}: {img_err}")
            return None

    except Exception as net_err:
        logger.debug(f"Network error fetching image {url}: {net_err}")
        return None


async def search_wikipedia_image(query: str) -> Optional[Path]:
    """Search Wikipedia PageImages API for authoritative topic lead image."""
    try:
        first_line = str(query or "").split("\n")[0].split("\r")[0].strip()
        clean_q = " ".join(re.sub(r"[^\w\s-]", " ", first_line).split()[:5]).strip()
        if not clean_q:
            return None
        headers = {"User-Agent": USER_AGENT}
        params = {
            "action": "query",
            "titles": clean_q,
            "prop": "pageimages",
            "piprop": "original",
            "format": "json",
        }

        async with httpx.AsyncClient(headers=headers, timeout=4.0) as client:
            r = await client.get("https://en.wikipedia.org/w/api.php", params=params)
            if r.status_code != 200:
                return None

            data = r.json()
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid == "-1":
                    continue
                orig = page.get("original", {})
                img_url = orig.get("source")
                if img_url and not img_url.lower().endswith(".svg"):
                    saved = await _download_and_optimize_image(img_url, filename_prefix=clean_q)
                    if saved:
                        return saved
    except Exception as e:
        logger.debug(f"Wikipedia image search failed for '{query}': {e}")
    return None


async def search_wikimedia_commons_image(query: str) -> Optional[Path]:
    """Search Wikimedia Commons for high-quality photos on the topic."""
    try:
        first_line = str(query or "").split("\n")[0].split("\r")[0].strip()
        clean_q = " ".join(re.sub(r"[^\w\s-]", " ", first_line).split()[:5]).strip()
        if not clean_q:
            return None
        headers = {"User-Agent": USER_AGENT}
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": clean_q,
            "gsrnamespace": 6,  # File: namespace
            "gsrlimit": 5,
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "format": "json",
        }

        async with httpx.AsyncClient(headers=headers, timeout=4.0) as client:
            r = await client.get("https://commons.wikimedia.org/w/api.php", params=params)
            if r.status_code != 200:
                return None

            data = r.json()
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                ii_list = page.get("imageinfo", [])
                if not ii_list:
                    continue
                ii = ii_list[0]
                mime = str(ii.get("mime", "")).lower()
                img_url = ii.get("url")

                if ("jpeg" in mime or "png" in mime or "webp" in mime) and img_url:
                    saved = await _download_and_optimize_image(img_url, filename_prefix=clean_q)
                    if saved:
                        return saved
    except Exception as e:
        logger.debug(f"Wikimedia Commons search failed for '{query}': {e}")
    return None


async def search_openverse_image(query: str) -> Optional[Path]:
    """Fallback search on Openverse for open-access photography."""
    try:
        first_line = str(query or "").split("\n")[0].split("\r")[0].strip()
        clean_q = " ".join(re.sub(r"[^\w\s-]", " ", first_line).split()[:5]).strip()
        if not clean_q:
            return None
        headers = {"User-Agent": USER_AGENT}
        params = {
            "q": clean_q,
            "page_size": 3,
        }

        async with httpx.AsyncClient(headers=headers, timeout=4.0) as client:
            r = await client.get("https://api.openverse.org/v1/images/", params=params)
            if r.status_code != 200:
                return None

            results = r.json().get("results", [])
            for item in results:
                img_url = item.get("url")
                if img_url and any(ext in img_url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                    saved = await _download_and_optimize_image(img_url, filename_prefix=clean_q)
                    if saved:
                        return saved
    except Exception as e:
        logger.debug(f"Openverse search failed for '{query}': {e}")
    return None


async def fetch_relevant_image(query: str, fallback_topic: Optional[str] = None) -> Optional[Path]:
    """
    Search across multiple open image providers to find and download a relevant picture.
    Tries: Wikipedia lead image -> Wikimedia Commons -> Openverse -> fallback topic.
    """
    if not query or not query.strip():
        return None

    # 1. Wikipedia Lead Photo
    img = await search_wikipedia_image(query)
    if img:
        return img

    # 2. Wikimedia Commons Photo Search
    img = await search_wikimedia_commons_image(query)
    if img:
        return img

    # 3. Openverse Photography
    img = await search_openverse_image(query)
    if img:
        return img

    # 4. If query was specific and failed, try the broader topic
    if fallback_topic and fallback_topic.lower().strip() != query.lower().strip():
        img = await search_wikipedia_image(fallback_topic)
        if img:
            return img
        img = await search_wikimedia_commons_image(fallback_topic)
        if img:
            return img

    return None
