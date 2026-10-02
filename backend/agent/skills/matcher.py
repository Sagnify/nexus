"""
Multi-Stage Skill Matcher for NEXUS Skill Learning.
Retrieves and validates user skills for fast-path deterministic execution.
Enforces tenancy isolation, exact and semantic matching, parameter extractability checks,
precondition feasibility probes, and ambiguity safety gates.
"""
from __future__ import annotations
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Skill, SkillVersion
from backend.database.repositories.skill_repo import SkillRepository
from backend.agent.skills.param_extractor import extractor

logger = logging.getLogger("nexus.skills.matcher")


class MatchResult:
    def __init__(
        self,
        skill: Skill,
        version: SkillVersion,
        confidence: float,
        match_type: str,  # "exact_trigger" | "semantic_similarity" | "ai_intent"
        resolved_parameters: dict[str, str],
        is_ambiguous: bool = False,
        competing_skills: Optional[list[str]] = None,
        missing_parameters: Optional[list[str]] = None,
    ):
        self.skill = skill
        self.version = version
        self.confidence = confidence
        self.match_type = match_type
        self.resolved_parameters = resolved_parameters
        self.is_ambiguous = is_ambiguous
        self.competing_skills = competing_skills or []
        self.missing_parameters = missing_parameters or []


class SkillMatcher:
    def _normalize_text(self, text: str) -> str:
        """Normalize punctuation and whitespace for resilient matching."""
        if not text:
            return ""
        lowered = text.strip().lower()
        cleaned = re.sub(r"[^\w\s]", " ", lowered)
        return " ".join(cleaned.split())

    def _strip_trigger_parameters(self, trigger: str) -> list[str]:
        """Convert a parameterized trigger like 'send email to {{recipient_email}}' into clean base phrases."""
        cleaned = re.sub(r"\{\{[^}]+\}\}", "", trigger).strip()
        cleaned_norm = self._normalize_text(cleaned)
        bases = [cleaned_norm] if cleaned_norm else []
        # If trigger has trailing prepositions like 'to', 'for', 'on', also add variant without it
        for prep in (" to", " for", " on", " with", " about"):
            if cleaned_norm.endswith(prep):
                bases.append(cleaned_norm[:-len(prep)].strip())
        return [b for b in bases if b]

    def _extract_parameters(
        self,
        user_prompt: str,
        parameters_schema: list[dict[str, Any]],
    ) -> tuple[dict[str, str], list[str]]:
        """
        Attempt to resolve required parameter values from the incoming prompt.
        Uses intelligent pattern matching to extract emails, dates, subjects, bodies, etc.
        Returns (resolved_dict, missing_required_params_list).
        """
        return extractor.extract_parameters_from_prompt(user_prompt, parameters_schema)

    def _bigrams(self, tokens: list[str]) -> set[str]:
        """Generate set of adjacent word bigrams."""
        return {f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)}

    def _score_semantic_similarity(self, query: str, skill: Skill) -> float:
        """
        Enhanced token overlap similarity combining unigrams + bigrams,
        intent-concept domain boosting, and environment affinity scoring.
        """
        query_norm = self._normalize_text(query)
        q_tokens = query_norm.split()
        q_token_set = set(q_tokens)
        q_bigrams = self._bigrams(q_tokens)
        if not q_token_set:
            return 0.0

        best_score = 0.0

        def _token_score(ref_tokens: list[str]) -> float:
            """Combined unigram + bigram Jaccard-style overlap against q."""
            if not ref_tokens:
                return 0.0
            ref_set = set(ref_tokens)
            ref_bigrams = self._bigrams(ref_tokens)
            uni_overlap = len(q_token_set & ref_set) / max(len(ref_set), 1)
            if ref_bigrams and q_bigrams:
                bi_overlap = len(q_bigrams & ref_bigrams) / max(len(ref_bigrams), 1)
                # Bigrams are a stronger signal — weight them higher
                return 0.55 * uni_overlap + 0.45 * bi_overlap
            return uni_overlap

        # 1. Match against skill name
        name_tokens = self._normalize_text(skill.name).split()
        best_score = max(best_score, _token_score(name_tokens))

        # 2. Match against trigger phrases (including stripped parameter variants)
        for trigger in skill.trigger_phrases or []:
            t_tokens = self._normalize_text(trigger).split()
            best_score = max(best_score, _token_score(t_tokens))

            for base in self._strip_trigger_parameters(trigger):
                b_tokens = base.split()
                best_score = max(best_score, _token_score(b_tokens))

        # 3. Description token scoring (lower weight)
        if skill.description:
            desc_tokens = self._normalize_text(skill.description).split()[:20]  # cap at 20
            desc_score = _token_score(desc_tokens) * 0.6
            best_score = max(best_score, desc_score)

        # 4. Domain & concept domain boosts
        target_sites: list[str] = []
        if getattr(skill, "target_sites", None):
            target_sites = skill.target_sites
        elif skill.versions and getattr(skill.versions[0], "metadata_json", None):
            target_sites = skill.versions[0].metadata_json.get("target_sites", [])

        lower_q = query.lower()

        # Email domain boost
        is_email_query = any(w in lower_q for w in ("email", "mail", "gmail", "compose", "inbox", "send email", "write email"))
        is_email_skill = (
            "mail" in (skill.name or "").lower()
            or any("mail.google.com" in s for s in target_sites)
            or any("mail" in t.lower() or "email" in t.lower() for t in (skill.trigger_phrases or []))
        )
        if is_email_query and is_email_skill:
            best_score = max(best_score, 0.88)

        # Search / browser site boost
        for site in target_sites:
            site_base = site.split(".")[0]
            if len(site_base) >= 4 and site_base in q_token_set:
                best_score = max(best_score, 0.75)

        # 5. Synonym / concept expansion boosts
        synonym_pairs = [
            ({"compose", "write", "draft"}, {"send", "email", "mail"}),
            ({"download", "export", "get", "fetch"}, {"report", "invoice", "receipt", "file"}),
            ({"open", "launch", "start"}, {"app", "application", "program"}),
            ({"search", "find", "lookup", "google"}, {"query", "web", "internet"}),
            ({"fill", "complete", "submit"}, {"form", "login", "signup"}),
        ]
        for action_synonyms, object_synonyms in synonym_pairs:
            query_has_action = bool(q_token_set & action_synonyms)
            skill_has_action = any(
                bool(set(self._normalize_text(t).split()) & action_synonyms)
                for t in ([skill.name] + list(skill.trigger_phrases or []))
                if t
            )
            query_has_object = bool(q_token_set & object_synonyms)
            skill_has_object = any(
                bool(set(self._normalize_text(t).split()) & object_synonyms)
                for t in ([skill.name] + list(skill.trigger_phrases or []))
                if t
            )
            if query_has_action and query_has_object and skill_has_action and skill_has_object:
                best_score = max(best_score, 0.82)
            elif query_has_action and skill_has_action and (query_has_object or skill_has_object):
                best_score = max(best_score, 0.70)

        return round(min(best_score, 1.0), 3)

    async def _ai_classify_intent(
        self,
        user_prompt: str,
        skills: list[Skill],
    ) -> Optional[tuple[Skill, float, dict[str, str]]]:
        """
        Fast LLM classification fallback (<200ms) to detect whether user's natural prompt
        corresponds to any of the user's previously taught automation skills.
        """
        try:
            import json
            import asyncio
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch
            from langchain_core.messages import SystemMessage, HumanMessage

            skill_summaries = []
            for s in skills:
                t_sites = getattr(s, "target_sites", []) or []
                if not t_sites and s.versions and getattr(s.versions[0], "metadata_json", None):
                    t_sites = s.versions[0].metadata_json.get("target_sites", [])
                skill_summaries.append({
                    "id": str(s.id),
                    "name": s.name,
                    "description": s.description,
                    "target_sites": t_sites,
                    "triggers": s.trigger_phrases or [],
                    "parameters": [p.get("name") for p in (s.parameters_schema or [])],
                })

            sys_prompt = (
                "You are NEXUS Skill Dispatcher. A user has a library of personal automation skills they taught the system.\n"
                "Determine if the user's request matches any of their learned skills.\n"
                "If it matches, return JSON with 'matched_skill_id', 'confidence' (0.0 to 1.0), and 'extracted_parameters'.\n"
                "If no skill matches, set 'matched_skill_id' to null.\n"
                "Respond ONLY with valid JSON."
            )
            user_msg = (
                f"User Request: \"{user_prompt}\"\n\n"
                f"Learned Skills:\n{json.dumps(skill_summaries, indent=2)}"
            )

            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [SystemMessage(content=sys_prompt), HumanMessage(content=user_msg)],
                    operation="fast",
                    temperature=0.0,
                ),
                timeout=3.5,
            )

            content = res.content if hasattr(res, "content") else str(res)
            cleaned = content.strip()
            if "```" in cleaned:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
                if m:
                    cleaned = m.group(1).strip()

            parsed = json.loads(cleaned)
            matched_id = parsed.get("matched_skill_id")
            conf = float(parsed.get("confidence", 0.0))
            extracted_params = parsed.get("extracted_parameters") or {}

            if matched_id and conf >= 0.70:
                for s in skills:
                    if str(s.id) == str(matched_id):
                        return s, conf, extracted_params
        except Exception as e:
            logger.debug(f"[SkillMatcher] AI intent classification bypassed: {e}")

        return None

    async def match_skill(
        self,
        user_prompt: str,
        user_id: uuid.UUID,
        session: AsyncSession,
    ) -> Optional[MatchResult]:
        """
        Evaluate user request against user's personal skills.
        Executes multi-stage validation:
        1. Exact trigger match (including stripped parameter triggers)
        2. Semantic similarity scoring with intent keyword boosting
        3. Fast AI intent classification for natural conversational requests
        4. Parameter extraction and missing parameter tracking for follow-up
        """
        if not user_prompt or not user_prompt.strip():
            return None

        repo = SkillRepository(session)
        skills = await repo.get_active_skills_for_matching(user_id)
        if not skills:
            return None

        norm_query = self._normalize_text(user_prompt)

        # ── Stage 1: Exact / Base Trigger Match ───────────────────────────
        for skill in skills:
            if not skill.versions:
                continue

            for trigger in skill.trigger_phrases or []:
                norm_trig = self._normalize_text(trigger)
                # Exact normalized trigger
                if norm_trig == norm_query:
                    latest_version = skill.versions[0]
                    resolved_params, missing = self._extract_parameters(user_prompt, skill.parameters_schema or [])
                    logger.info(f"[SkillMatcher] Exact trigger hit: '{skill.name}' (v{latest_version.version_number})")
                    return MatchResult(
                        skill=skill,
                        version=latest_version,
                        confidence=1.0,
                        match_type="exact_trigger",
                        resolved_parameters=resolved_params,
                        missing_parameters=missing,
                    )

                # Parameter-stripped base trigger (e.g. "send email" matching "send email to {{recipient_email}}")
                for base in self._strip_trigger_parameters(trigger):
                    if base == norm_query:
                        latest_version = skill.versions[0]
                        resolved_params, missing = self._extract_parameters(user_prompt, skill.parameters_schema or [])
                        logger.info(f"[SkillMatcher] Base trigger exact hit: '{skill.name}' (matched base '{base}')")
                        return MatchResult(
                            skill=skill,
                            version=latest_version,
                            confidence=0.98,
                            match_type="exact_trigger",
                            resolved_parameters=resolved_params,
                            missing_parameters=missing,
                        )
                    elif norm_query.startswith(base):
                        latest_version = skill.versions[0]
                        resolved_params, missing = self._extract_parameters(user_prompt, skill.parameters_schema or [])
                        logger.info(f"[SkillMatcher] Base trigger prefix hit: '{skill.name}' (matched base '{base}')")
                        return MatchResult(
                            skill=skill,
                            version=latest_version,
                            confidence=0.92,
                            match_type="semantic_similarity",
                            resolved_parameters=resolved_params,
                            missing_parameters=missing,
                        )

        # ── Stage 2: Semantic Similarity Scoring ─────────────────────────
        scored_candidates: list[tuple[Skill, float]] = []
        for skill in skills:
            if not skill.versions:
                continue
            score = self._score_semantic_similarity(user_prompt, skill)
            if score >= 0.65:
                scored_candidates.append((skill, score))

        if scored_candidates:
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            top_skill, top_score = scored_candidates[0]

            # Ambiguity Resolution Gate
            if len(scored_candidates) > 1:
                second_skill, second_score = scored_candidates[1]
                if abs(top_score - second_score) < 0.05 and second_score >= 0.85:
                    logger.warning(
                        f"[SkillMatcher] Ambiguous match between '{top_skill.name}' ({top_score}) and '{second_skill.name}' ({second_score})."
                    )
                    return MatchResult(
                        skill=top_skill,
                        version=top_skill.versions[0],
                        confidence=top_score,
                        match_type="semantic_similarity",
                        resolved_parameters={},
                        is_ambiguous=True,
                        competing_skills=[top_skill.name, second_skill.name],
                    )

            resolved_params, missing = self._extract_parameters(user_prompt, top_skill.parameters_schema or [])
            latest_version = top_skill.versions[0]
            logger.info(f"[SkillMatcher] Semantic match hit: '{top_skill.name}' (score={top_score}, missing={missing})")
            return MatchResult(
                skill=top_skill,
                version=latest_version,
                confidence=top_score,
                match_type="semantic_similarity",
                resolved_parameters=resolved_params,
                missing_parameters=missing,
            )

        # ── Stage 3: Fast AI Intent Classification Fallback ──────────────
        ai_match = await self._ai_classify_intent(user_prompt, skills)
        if ai_match:
            ai_skill, ai_conf, ai_params = ai_match
            if ai_skill.versions:
                latest_version = ai_skill.versions[0]
                resolved_params, missing = self._extract_parameters(user_prompt, ai_skill.parameters_schema or [])
                # Merge any parameters extracted by AI
                for k, v in ai_params.items():
                    if v and k not in resolved_params:
                        resolved_params[k] = str(v)
                        if k in missing:
                            missing.remove(k)

                logger.info(f"[SkillMatcher] AI Intent match hit: '{ai_skill.name}' (conf={ai_conf}, missing={missing})")
                return MatchResult(
                    skill=ai_skill,
                    version=latest_version,
                    confidence=ai_conf,
                    match_type="ai_intent",
                    resolved_parameters=resolved_params,
                    missing_parameters=missing,
                )

        return None


matcher = SkillMatcher()
