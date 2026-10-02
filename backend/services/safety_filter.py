"""
NEXUS Safety & NSFW Sensitivity Filter (Backend Service)

Provides privacy-first query classification to prevent NSFW, pornographic,
or sexually explicit search queries from being used as recommendation or
autocomplete signals.

Features:
- Input-side signal exclusion (drops NSFW queries before computing recommendation patterns).
- Output-side candidate filtering (scrubs candidate lists).
- Benign context overrides for technical (cybersecurity, programming), scientific,
  cosmetics, and demographic usages.
- De-obfuscation and normalization (leetspeak, spaced characters).
- High-speed in-memory LRU cache.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SafetyClassificationResult:
    is_sensitive: bool
    sensitivity_category: Optional[str]
    recommendation_eligible: bool
    confidence: float
    classified_at: float
    reason: Optional[str] = None


# Leetspeak translation table
_LEET_TRANSLATIONS = str.maketrans({
    "@": "a", "4": "a",
    "3": "e",
    "1": "i", "!": "i", "|": "i",
    "0": "o",
    "$": "s", "5": "s",
    "+": "t",
    "*": "", "#": "",
})

_DOTTED_SEPARATORS_RE = re.compile(r"\b([a-z](?:[._\-][a-z])+)\b", re.I)
_SPACED_LETTERS_RE = re.compile(r"\b([a-z](?:\s+[a-z]){2,})\b", re.I)
_MULTI_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_safety(query: str) -> str:
    """Normalize query by stripping leetspeak and internal word separators."""
    text = query.lower().strip()
    # Handle single-character spaced/dotted sequences before leetspeak:
    # e.g. "p.o.r.n" -> "porn", "p_o_r_n" -> "porn"
    text = _DOTTED_SEPARATORS_RE.sub(lambda m: re.sub(r"[._\-]", "", m.group(1)), text)
    # e.g. "p o r n" (at least 3 single letters spaced) -> "porn"
    text = _SPACED_LETTERS_RE.sub(lambda m: re.sub(r"\s+", "", m.group(0)), text)
    text = text.translate(_LEET_TRANSLATIONS)
    return _MULTI_WHITESPACE_RE.sub(" ", text)


# Explicit sexual keywords that unconditionally trigger NSFW classification
STRICT_EXPLICIT_TERMS: set[str] = {
    "porn", "porno", "pornography", "pornstar", "xxx", "hentai", "erotica",
    "blowjob", "handjob", "cumshot", "deepthroat", "threesome", "gangbang",
    "cunnilingus", "fellatio", "masturbat", "masturbation", "orgasm",
    "dildo", "vibrator", "fleshlight", "sex toy", "sex toys", "onlyfans leak",
    "onlyfans leaks", "camgirl", "camgirls", "stripper", "strippers", "strip club",
    "stripclub", "milf", "bdsm", "bondage", "creampie", "hardcore porn",
    "softcore porn", "rule34", "r34", "nsfw", "smut", "lewd", "deepfake nude",
    "undress ai", "strip ai", "boobs", "tits", "titties", "pussy", "vagina",
    "penis", "cock", "dick pic", "dick pics", "nude pics", "send nudes",
    "escort service", "escort services", "hooker", "prostitute", "brothel",
    "cybersex", "sexting", "sext",
}

# Regex patterns for compound phrases and intent
EXPLICIT_PHRASE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:watch|free|download|stream)\s+(?:porn|xxx|sex|hentai|erotica)\b", re.I),
    re.compile(r"\b(?:nude|naked)\s+(?:pics|pictures|photos|video|videos|leak|leaks|girls|women|men|celebrity|celebrities)\b", re.I),
    re.compile(r"\b(?:sex|sexual)\s+(?:video|videos|tape|tapes|movie|movies|chat|clips|positions?|acts?)\b", re.I),
    re.compile(r"\b(?:how\s+to\s+have|wanna\s+have|want\s+to\s+have)\s+sex\b", re.I),
    re.compile(r"\b(?:hot\s+girls?|sexy\s+girls?|hot\s+women)\s+(?:strip|naked|undress|nude)\b", re.I),
    re.compile(r"\b(?:dirty\s+talk|erotic\s+roleplay|erotic\s+novel|smut\s+fanfic|adult\s+game|sex\s+game)\b", re.I),
    re.compile(r"\b(?:undress|strip)\s+(?:photo|photos|picture|pictures|app|filter)\b", re.I),
    re.compile(r"\b(?:anal|oral|group)\s+sex\b", re.I),
    re.compile(r"\brule\s*(?:34|3a)\b", re.I),
    re.compile(r"\br(?:34|3a)\b", re.I),
]

# False positive exceptions (Benign technical, scientific, demographic, cosmetics)
BENIGN_CONTEXT_RULES = [
    (
        re.compile(r"\bstrip(?:ping|ped|s)?\b", re.I),
        re.compile(r"\b(?:string|whitespace|split|code|python|pandas|dataframe|trim|regex|comic|cartoon|vegas\s+strip|gaza\s+strip|strip\s+plot|bacon|test\s+strip|power\s+strip|weather\s+strip|copper\s+strip|metal\s+strip)\b", re.I),
    ),
    (
        re.compile(r"\bpenetrat(?:ion|ing|e)\b", re.I),
        re.compile(r"\b(?:test|testing|tester|security|cyber|network|vulnerability|kali|audit|market|pricing|depth|radar|shield)\b", re.I),
    ),
    (
        re.compile(r"\badult(?:s)?\b", re.I),
        re.compile(r"\b(?:learning|education|literacy|supervision|demographic|novel|ya|young\s+adult|pediatric|medicine|care|patient|immunization|dose|ticket)\b", re.I),
    ),
    (
        re.compile(r"\bsex(?:ual)?\b", re.I),
        re.compile(r"\b(?:chromosome|chromosomes|ratio|biology|biological|determination|dimorphism|gender|demographics|survey|census|disaggregated|offender\s+registry)\b", re.I),
    ),
    (
        re.compile(r"\bnude(?:s)?\b", re.I),
        re.compile(r"\b(?:lipstick|makeup|nail\s+polish|shoes|heels|dress|color|palette|shades?|art\s+history|renaissance|statue|painting|sculpture)\b", re.I),
    ),
    (
        re.compile(r"\bhot\b", re.I),
        re.compile(r"\b(?:reload|reloading|fix|fixes|chocolate|coffee|dog|dogs|sauce|water|springs?|weather|temperature|topic|key|keys|spot|potato)\b", re.I),
    ),
]

# In-memory LRU Cache
_CACHE_MAX_SIZE = 1000
_classification_cache: dict[str, SafetyClassificationResult] = {}


def classify_query_safety(raw_query: str) -> SafetyClassificationResult:
    """
    Classifies a query for NSFW or sexually explicit sensitivity.
    Returns recommendation eligibility and detailed classification metadata.
    """
    query = raw_query.strip()
    if not query:
        return SafetyClassificationResult(
            is_sensitive=False,
            sensitivity_category=None,
            recommendation_eligible=True,
            confidence=1.0,
            classified_at=time.time(),
        )

    if query in _classification_cache:
        return _classification_cache[query]

    # Pre-check for numeric explicit phrases (like rule 34 / r34) before leetspeak transformations
    if re.search(r"\b(?:rule\s*34|r34)\b", query, re.I):
        res = SafetyClassificationResult(
            is_sensitive=True,
            sensitivity_category="sexual_intent",
            recommendation_eligible=False,
            confidence=0.98,
            classified_at=time.time(),
            reason="explicit_phrase_match: rule 34",
        )
        _cache_result(query, res)
        return res

    normalized = normalize_for_safety(query)
    words = set(normalized.split())

    # Step 1: Check for Benign Context Overrides first
    has_benign_override = False
    for trigger_re, benign_re in BENIGN_CONTEXT_RULES:
        if trigger_re.search(normalized) and benign_re.search(normalized):
            # Ensure no explicit sexual terms are present
            has_explicit = any(
                term in words or (term in normalized if " " in term else False)
                for term in STRICT_EXPLICIT_TERMS
            )
            if not has_explicit:
                has_benign_override = True
                break

    if has_benign_override:
        res = SafetyClassificationResult(
            is_sensitive=False,
            sensitivity_category=None,
            recommendation_eligible=True,
            confidence=0.95,
            classified_at=time.time(),
            reason="benign_context_override",
        )
        _cache_result(query, res)
        return res

    # Step 2: Strict explicit terms
    for term in STRICT_EXPLICIT_TERMS:
        if " " in term:
            if term in normalized:
                res = SafetyClassificationResult(
                    is_sensitive=True,
                    sensitivity_category="explicit_terms",
                    recommendation_eligible=False,
                    confidence=0.98,
                    classified_at=time.time(),
                    reason=f"explicit_term_match: {term}",
                )
                _cache_result(query, res)
                return res
        else:
            if term in words:
                res = SafetyClassificationResult(
                    is_sensitive=True,
                    sensitivity_category="explicit_terms",
                    recommendation_eligible=False,
                    confidence=0.98,
                    classified_at=time.time(),
                    reason=f"explicit_word_match: {term}",
                )
                _cache_result(query, res)
                return res

    # Step 3: Explicit phrase intent
    for pattern in EXPLICIT_PHRASE_PATTERNS:
        if pattern.search(normalized):
            res = SafetyClassificationResult(
                is_sensitive=True,
                sensitivity_category="sexual_intent",
                recommendation_eligible=False,
                confidence=0.95,
                classified_at=time.time(),
                reason="sexual_phrase_intent_detected",
            )
            _cache_result(query, res)
            return res

    # Step 4: Suggestive nudity
    if re.search(r"\b(?:naked|nude|undressed)\b", normalized, re.I):
        res = SafetyClassificationResult(
            is_sensitive=True,
            sensitivity_category="suggestive",
            recommendation_eligible=False,
            confidence=0.85,
            classified_at=time.time(),
            reason="suggestive_unqualified_nudity",
        )
        _cache_result(query, res)
        return res

    # Safe
    res = SafetyClassificationResult(
        is_sensitive=False,
        sensitivity_category=None,
        recommendation_eligible=True,
        confidence=0.99,
        classified_at=time.time(),
    )
    _cache_result(query, res)
    return res


def _cache_result(key: str, res: SafetyClassificationResult) -> None:
    if len(_classification_cache) >= _CACHE_MAX_SIZE:
        first_key = next(iter(_classification_cache))
        del _classification_cache[first_key]
    _classification_cache[key] = res


def filter_safe_recommendations(items: list[dict[str, Any]], query_key: str = "prompt") -> list[dict[str, Any]]:
    """Filters out any recommendation candidate item that is classified as NSFW or sensitive."""
    filtered: list[dict[str, Any]] = []
    for item in items:
        val = item.get(query_key) or ""
        if not val or not isinstance(val, str):
            continue
        classification = classify_query_safety(val)
        if classification.recommendation_eligible:
            filtered.append(item)
    return filtered
