"""
Skill Compiler for NEXUS Skill Learning.
Synthesizes dynamic parameter templates ({{param}}), formal preconditions and postconditions,
and validates compiled action schemas before human review and database persistence.
"""
from __future__ import annotations
import logging
import re
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.agent.skills.semanticizer import RawSemanticAction

from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger("nexus.skills.compiler")


# --- Formal Validation Schemas ---

class SelectorBundleSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    testId: Optional[str] = None
    ariaLabel: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    id: Optional[str] = None
    cssPath: Optional[str] = None
    xpath: Optional[str] = None
    textAnchor: Optional[str] = None


class ConditionSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    check_type: str  # "url_contains" | "element_visible" | "file_created" | "window_active"
    target: str
    timeout_seconds: float = 6.0


class CompiledStepSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_id: str
    title: str
    action_type: str
    execution_engine: str = "browser"
    target_app: Optional[str] = None
    url: Optional[str] = None
    selector_bundle: Optional[SelectorBundleSchema] = None
    value_template: Optional[str] = None
    parameter_references: List[str] = Field(default_factory=list)
    is_idempotent: bool = False
    preconditions: List[ConditionSchema] = Field(default_factory=list)
    postconditions: List[ConditionSchema] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: str = "string"  # string, email, date, number, filepath, selection, choice
    description: str
    required: bool = True
    default_value: Optional[str] = None
    prompt_text: Optional[str] = None  # Custom prompt to ask user
    placeholder: Optional[str] = None  # Placeholder text for input
    options: Optional[List[str]] = None  # For selection/choice types


class CompiledSkillDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    description: str
    category: str = "general"
    environment: str = "mixed"
    trigger_phrases: List[str] = Field(default_factory=list)
    parameters_schema: List[ParameterDefinition] = Field(default_factory=list)
    steps: List[CompiledStepSchema] = Field(default_factory=list)
    preconditions: List[ConditionSchema] = Field(default_factory=list)
    postconditions: List[ConditionSchema] = Field(default_factory=list)
    target_sites: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)



# --- Common Entity Extraction Patterns ---
DATE_PATTERNS = [
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b",
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{2}/\d{2}/\d{4}\b",
    r"\b\d{4}\b",
]
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"

DISTILLATION_SYSTEM_PROMPT = """You are NEXUS Skill Distiller.
Convert user-demonstrated actions into a clean, minimal, dynamic, reusable workflow.
1. PURGE NOISE: Completely discard actions from unrelated background sites/apps (e.g. Google Meet, blank tabs, ad popups) and accidental misclicks. Keep only essential steps for the primary task.
2. ROUTE REPAIR FROM EVIDENCE:
    - Consider the entire recorded sequence and workflow intent together, not one action in isolation.
    - Put an observed navigation before interactions that depend on that page, even if capture delivery reordered the events.
    - Prefer URLs and sites actually present in the recording. Never invent a route or claim an unobserved action succeeded.
    - When changing order, preserve each source action's original_step_index so its recorded selector bundle is restored.
3. DYNAMIC INPUT GENERALIZATION:
   - Generalize user-typed values with mustache templates: {{recipient_email}}, {{subject}}, {{body}}, {{search_query}}, {{target_date}}, {{amount}}, etc.
   - For every parameterized step, set "value_template" to "{{param}}" and "parameter_references": ["param"].
   - In "parameters_schema", declare each parameter: name, type ("string"|"email"|"date"|"number"|"filepath"), description, required (bool), default_value.
4. PRESERVE SELECTORS: Include "original_step_index" (matching input "idx") for each step so DOM selectors are retained. Never synthesize a selector for an observed interaction.
5. ZERO EMOJIS: Never use emojis in names, descriptions, or trigger phrases.

Respond ONLY with valid JSON:
{
  "name": "Skill Name",
  "description": "Clear explanation of what the skill does",
  "category": "communication" | "browser" | "productivity" | "general",
  "target_sites": ["domain.com"],
  "trigger_phrases": ["action phrase", "action phrase to {{recipient_email}}"],
  "parameters_schema": [
    {"name": "recipient_email", "type": "email", "description": "Recipient email", "required": true, "default_value": "..."}
  ],
  "steps": [
    {"original_step_index": 0, "title": "Navigate to...", "action_type": "browser_navigate", "execution_engine": "browser", "url": "https://...", "value_template": null, "parameter_references": []},
    {"original_step_index": 1, "title": "Type...", "action_type": "browser_type", "execution_engine": "browser", "value_template": "{{param}}", "parameter_references": ["param"]}
  ]
}"""


class SkillCompiler:
    def _extract_parameters_from_value(
        self,
        value: str,
        prompt_intent: Optional[str] = None,
        field_context: Optional[str] = None,
    ) -> tuple[str, list[ParameterDefinition]]:
        """Identify dynamic tokens in user entered text and generate mustache templates."""
        if not value or value.startswith("[REDACTED"):
            return value, []

        params: list[ParameterDefinition] = []
        templated_val = value

        # Check if the overall intent indicates search
        is_search_intent = any(term in (prompt_intent or "").lower() for term in ("search", "find", "lookup", "google", "query"))

        # Explicit search input box check
        if field_context:
            fc_low = field_context.lower()
            is_search_box = (
                fc_low in ("search", "search box", "search query", "q", "query")
                or any(term in fc_low for term in ("search input", "search-input", "input#search", "search_query"))
            )
            # Only treat as dynamic search_query if intent was to search or field is unambiguously a search box
            if is_search_box and (is_search_intent or len(value.split()) <= 6):
                param_name = "search_query"
                params.append(
                    ParameterDefinition(
                        name=param_name,
                        type="string",
                        description="Search term or query",
                        required=is_search_intent,
                        default_value=value if not is_search_intent else None,
                    )
                )
                return f"{{{{{param_name}}}}}", params

        # 1. Match dates
        for pat in DATE_PATTERNS:
            match = re.search(pat, value, re.IGNORECASE)
            if match:
                matched_str = match.group(0)
                param_name = "target_date"
                templated_val = templated_val.replace(matched_str, f"{{{{{param_name}}}}}")
                params.append(
                    ParameterDefinition(
                        name=param_name,
                        type="date",
                        description="Date to use for this workflow",
                        required=True,
                        default_value=None,
                    )
                )
                break

        # 2. Match email addresses
        email_match = re.search(EMAIL_PATTERN, templated_val)
        if email_match:
            matched_email = email_match.group(0)
            param_name = "recipient_email"
            templated_val = templated_val.replace(matched_email, f"{{{{{param_name}}}}}")
            params.append(
                ParameterDefinition(
                    name=param_name,
                    type="email",
                    description="Target email address",
                    required=True,
                    default_value=None,
                )
            )

        # 3. Match field semantic context if field is known
        if field_context and len(params) == 0:
            fc = field_context.lower()
            if "subject" in fc:
                param_name = "subject"
                params.append(
                    ParameterDefinition(
                        name=param_name,
                        type="string",
                        description="Email subject line",
                        required=True,
                        default_value=None,
                    )
                )
                templated_val = f"{{{{{param_name}}}}}"
            elif "body" in fc or "message" in fc or (not fc and len(value.split()) > 4):
                param_name = "body"
                params.append(
                    ParameterDefinition(
                        name=param_name,
                        type="string",
                        description="Message body text",
                        required=True,
                        default_value=None,
                    )
                )
                templated_val = f"{{{{{param_name}}}}}"

        # 4. Match numeric amounts / currency / quantities
        if len(params) == 0 and field_context:
            fc = field_context.lower()
            if any(term in fc for term in ("amount", "price", "cost", "total", "budget", "quantity", "count", "number")):
                num_match = re.search(r"\b\d+(?:\.\d+)?\b", value)
                if num_match:
                    matched_num = num_match.group(0)
                    param_name = "amount" if any(t in fc for t in ("amount", "price", "cost", "total", "budget")) else "quantity"
                    templated_val = templated_val.replace(matched_num, f"{{{{{param_name}}}}}")
                    params.append(
                        ParameterDefinition(
                            name=param_name,
                            type="number",
                            description=f"Dynamic {param_name} value",
                            required=True,
                            default_value=None,
                        )
                    )

        # 5. Match prompt keywords if user typed specific prompt query
        if prompt_intent and is_search_intent and len(params) == 0:
            prompt_words = [w.strip() for w in prompt_intent.split() if len(w) > 3]
            for word in prompt_words:
                if word.lower() in value.lower() and len(word) >= 4:
                    param_name = "search_query"
                    templated_val = templated_val.replace(word, f"{{{{{param_name}}}}}")
                    params.append(
                        ParameterDefinition(
                            name=param_name,
                            type="string",
                            description="Search term or query",
                            required=True,
                            default_value=None,
                        )
                    )
                    break

        return templated_val, params

    def compile(
        self,
        raw_actions: List[RawSemanticAction],
        prompt_intent: Optional[str] = None,
        skill_name: Optional[str] = None,
        category: str = "general",
    ) -> CompiledSkillDraft:
        """Compile raw semantic actions into a validated, parameterized workflow draft."""
        if not raw_actions:
            from backend.agent.skills.semanticizer import RawSemanticAction
            raw_actions = [
                RawSemanticAction(
                    action_type="browser_navigate",
                    execution_engine="browser",
                    title="Open Target Page",
                    url="https://google.com",
                    target_app="Chrome",
                )
            ]

        # Heuristic noise filtering: if actions touch a primary app (like Gmail or other app)
        # but also background tabs like meet.google.com, filter out meet.google.com
        all_hosts = set()
        from urllib.parse import urlparse
        for act in raw_actions:
            u = act.url or (act.value if act.action_type == "browser_navigate" else None)
            if u and (u.startswith("http://") or u.startswith("https://")):
                try:
                    h = urlparse(u).netloc.lower().split(":")[0]
                    if h.startswith("www."):
                        h = h[4:]
                    if h:
                        all_hosts.add(h)
                except Exception:
                    pass

        # Only filter meet.google.com when there are OTHER non-meet, non-blank-tab hosts present.
        # The old heuristic triggered whenever any non-google host existed, which over-filtered.
        non_noise_hosts = {h for h in all_hosts if h and h not in ("newtab", "about:blank", "")}
        has_real_target = bool(non_noise_hosts - {"meet.google.com", "google.com", "accounts.google.com"})
        filtered_actions = []
        for act in raw_actions:
            # Drop Google Meet background tab only when user was clearly working somewhere else
            if has_real_target and act.url and "meet.google.com" in act.url.lower():
                continue
            filtered_actions.append(act)

        if not filtered_actions:
            filtered_actions = raw_actions

        # Filter initial lingering tab navigation if immediately followed by another navigation without interactions
        if len(filtered_actions) > 1:
            first = filtered_actions[0]
            is_initial = (
                first.action_type == "browser_navigate"
                and (
                    first.metadata.get("action") == "initial_page"
                    or (first.url and any(noise in first.url.lower() for noise in ("google.com/search", "chrome://", "about:blank", "newtab")))
                )
            )
            if is_initial:
                # Check if user interacted with this initial page before the next navigation
                has_subsequent_interaction = False
                for act in filtered_actions[1:]:
                    if act.action_type in ("browser_click", "browser_type", "desktop_click", "desktop_type"):
                        has_subsequent_interaction = True
                        break
                    if act.action_type == "browser_navigate":
                        break
                if not has_subsequent_interaction:
                    filtered_actions = filtered_actions[1:]

        compiled_steps: List[CompiledStepSchema] = []
        all_params: Dict[str, ParameterDefinition] = {}
        environments = set()

        for idx, act in enumerate(filtered_actions):
            environments.add(act.execution_engine)

            # Idempotency determination
            is_idempotent = act.action_type in ("browser_navigate", "desktop_focus", "browser_press")
            if "submit" in act.title.lower() or "pay" in act.title.lower() or "delete" in act.title.lower() or "send" in act.title.lower():
                is_idempotent = False

            # Parameter generalization with field context - ONLY for typing actions
            val_template = act.value
            step_param_refs = []
            if act.action_type in ("browser_type", "desktop_type") and act.value and not act.is_sensitive:
                sel = act.selector_bundle or {}
                # Only use input-specific field context attributes, not arbitrary action titles
                field_ctx = sel.get("ariaLabel") or sel.get("placeholder") or sel.get("name") or ""
                templated, extracted_params = self._extract_parameters_from_value(act.value, prompt_intent, field_ctx)
                val_template = templated
                for p in extracted_params:
                    all_params[p.name] = p
                    if p.name not in step_param_refs:
                        step_param_refs.append(p.name)
            elif act.action_type == "browser_navigate":
                val_template = None

            # Preconditions and Postconditions
            preconds: List[ConditionSchema] = []
            postconds: List[ConditionSchema] = []

            if act.action_type == "browser_navigate" and act.url:
                domain = urlparse(act.url).netloc
                if domain:
                    postconds.append(ConditionSchema(check_type="url_contains", target=domain))

            if act.action_type in ("browser_click", "browser_type") and act.selector_bundle:
                best_sel = (
                    act.selector_bundle.get("testId")
                    or act.selector_bundle.get("ariaLabel")
                    or act.selector_bundle.get("id")
                    or act.selector_bundle.get("cssPath")
                )
                if best_sel:
                    preconds.append(ConditionSchema(check_type="element_visible", target=best_sel))

            selector_bundle = None
            if act.selector_bundle and isinstance(act.selector_bundle, dict):
                try:
                    selector_bundle = SelectorBundleSchema(**act.selector_bundle)
                except Exception:
                    selector_bundle = None

            exec_engine = act.execution_engine if act.execution_engine in ("browser", "desktop", "system") else "browser"

            step = CompiledStepSchema(
                step_id=act.step_id or f"step-{uuid.uuid4().hex[:6]}",
                title=act.title or f"Step {idx + 1}",
                action_type=act.action_type or "browser_click",
                execution_engine=exec_engine,
                target_app=act.target_app,
                url=act.url,
                selector_bundle=selector_bundle,
                value_template=val_template,
                parameter_references=step_param_refs,
                is_idempotent=is_idempotent,
                preconditions=preconds,
                postconditions=postconds,
                metadata=act.metadata or {},
            )
            compiled_steps.append(step)

        if not compiled_steps:
            compiled_steps.append(
                CompiledStepSchema(
                    step_id=f"step-{uuid.uuid4().hex[:6]}",
                    title="Perform Workflow Action",
                    action_type="browser_navigate",
                    execution_engine="browser",
                    url="https://google.com",
                    preconditions=[],
                    postconditions=[],
                )
            )

        # Extract target sites & applications from demonstration actions
        extracted_sites: List[str] = []
        for act in filtered_actions:
            raw_url = act.url or (act.value if act.action_type == "browser_navigate" else None)
            if raw_url and (raw_url.startswith("http://") or raw_url.startswith("https://")):
                try:
                    host = urlparse(raw_url).netloc.lower().split(":")[0]
                    if host.startswith("www."):
                        host = host[4:]
                    # Filter out meet if other sites exist
                    if host == "meet.google.com" and len(all_hosts) > 1:
                        continue
                    if host and host not in extracted_sites:
                        extracted_sites.append(host)
                except Exception:
                    pass

        primary_site = extracted_sites[0] if extracted_sites else None
        starting_url = filtered_actions[0].url if (filtered_actions and filtered_actions[0].url) else None

        workflow_preconditions: List[ConditionSchema] = []
        if primary_site:
            workflow_preconditions.append(ConditionSchema(check_type="url_contains", target=primary_site))

        # Infer overall environment
        if len(environments) > 1:
            overall_env = "mixed"
        elif "desktop" in environments:
            overall_env = "desktop"
        else:
            overall_env = "browser"

        # Generate trigger phrases (ZERO EMOJIS, no noise site phrases)
        triggers = []
        if prompt_intent:
            cleaned = prompt_intent.strip().lower()
            # Remove any emojis
            cleaned = re.sub(r"[^\x00-\x7F]+", "", cleaned).strip()
            if cleaned:
                triggers.append(cleaned)
                no_punct = re.sub(r"[^\w\s]", "", cleaned).strip()
                if no_punct and no_punct != cleaned and no_punct not in triggers:
                    triggers.append(no_punct)

                # Add parameterized variations if parameters exist
                if "recipient_email" in all_params:
                    triggers.append(f"{cleaned} to {{{{recipient_email}}}}")
                if "search_query" in all_params:
                    triggers.append(f"{cleaned} for {{{{search_query}}}}")

                if primary_site and "meet" not in primary_site:
                    site_label = primary_site.split(".")[0]
                    if site_label and site_label not in cleaned:
                        triggers.append(f"{cleaned} on {site_label}")

        draft_name = skill_name or (prompt_intent.title() if prompt_intent else f"Demonstrated Skill {uuid.uuid4().hex[:4]}")
        desc = (
            f"Automated workflow learned from demonstration on {', '.join(extracted_sites)}: {prompt_intent or draft_name}"
            if extracted_sites
            else f"Automated workflow learned from demonstration: {prompt_intent or draft_name}"
        )

        draft = CompiledSkillDraft(
            name=draft_name[:255],
            description=desc,
            category=category,
            environment=overall_env,
            trigger_phrases=triggers,
            parameters_schema=list(all_params.values()),
            steps=compiled_steps,
            preconditions=workflow_preconditions,
            target_sites=extracted_sites,
            metadata={
                "target_sites": extracted_sites,
                "primary_site": primary_site,
                "starting_url": starting_url,
            },
        )

        return draft

    async def compile_with_ai(
        self,
        raw_actions: List[RawSemanticAction],
        prompt_intent: Optional[str] = None,
        skill_name: Optional[str] = None,
        category: str = "general",
    ) -> CompiledSkillDraft:
        """
        Synthesize raw demonstration actions using LLM reasoning to:
        1. Completely filter out noise, background apps/tabs (e.g. Google Meet), and accidental clicks.
        2. Parameterize concrete inputs (email, subject, body, queries) into dynamic templates ({{recipient_email}}, {{subject}}, {{body}}).
        3. Retain exact DOM selectors via original_step_index mapping.
        4. Generate clean natural triggers without emojis or noisy artifacts.
        Falls back seamlessly to deterministic compile() if LLM fails or is unconfigured.
        """
        if not raw_actions:
            return self.compile([], prompt_intent, skill_name, category)

        # Fast path: For short sequences (<=2 actions), deterministic compilation is instant and perfect
        if len(raw_actions) <= 2:
            return self.compile(raw_actions, prompt_intent, skill_name, category)

        try:
            import json
            import asyncio
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch
            from langchain_core.messages import SystemMessage, HumanMessage

            actions_payload = []
            for idx, act in enumerate(raw_actions):
                sel = act.selector_bundle or {}
                selector_desc = (
                    sel.get("ariaLabel")
                    or sel.get("name")
                    or sel.get("textAnchor")
                    or sel.get("testId")
                    or sel.get("id")
                )
                val = act.value
                if val and act.is_sensitive:
                    val = "[REDACTED]"
                actions_payload.append({
                    "original_step_index": idx,
                    "action_type": act.action_type,
                    "execution_engine": act.execution_engine,
                    "title": act.title,
                    "url": act.url,
                    "value": val,
                    "target_element": selector_desc,
                    "selector_bundle": sel,
                    "metadata": act.metadata or {},
                })

            user_prompt = (
                f"Workflow Intent: {prompt_intent or skill_name or 'Automated Task'}\n"
                f"Actions ({len(raw_actions)}):\n"
                f"{json.dumps(actions_payload, separators=(',', ':'))}\n"
                f"Distill essential steps with dynamic parameter templates ({{{{param}}}}). Return JSON only."
            )

            logger.info(
                "[SkillCompiler] 🚀 Starting AI distillation for %d demonstration actions (intent: '%s')...",
                len(raw_actions),
                prompt_intent or skill_name or "Workflow",
            )

            # Hard ceiling: 6s total for AI distillation (2 attempts × 3s each in model_router)
            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [
                        SystemMessage(content=DISTILLATION_SYSTEM_PROMPT),
                        HumanMessage(content=user_prompt),
                    ],
                    operation="fast",
                    temperature=0.1,
                    max_attempts=2,
                    per_attempt_timeout=3.5,
                    max_tokens=600,
                ),
                timeout=7.0,
            )

            content = res.content if hasattr(res, "content") else str(res)
            cleaned_json = content.strip()
            if "```" in cleaned_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_json)
                if match:
                    cleaned_json = match.group(1).strip()

            parsed = json.loads(cleaned_json)
            raw_steps = parsed.get("steps", [])
            if not raw_steps or not isinstance(raw_steps, list):
                raise ValueError("AI distillation returned empty steps list.")

            compiled_steps: List[CompiledStepSchema] = []
            for s_idx, st in enumerate(raw_steps):
                orig_idx = st.get("original_step_index")
                # LLMs sometimes return the index as a string (e.g. "0") — normalise to int
                if isinstance(orig_idx, str):
                    try:
                        orig_idx = int(orig_idx)
                    except (ValueError, TypeError):
                        orig_idx = None
                orig_act: Optional[RawSemanticAction] = None
                if isinstance(orig_idx, int) and 0 <= orig_idx < len(raw_actions):
                    orig_act = raw_actions[orig_idx]

                action_type = st.get("action_type") or (orig_act.action_type if orig_act else "browser_click")
                exec_engine = st.get("execution_engine") or (orig_act.execution_engine if orig_act else "browser")
                if exec_engine not in ("browser", "desktop", "system"):
                    exec_engine = "browser"
                step_title = st.get("title") or (orig_act.title if orig_act else f"Step {s_idx + 1}")
                url = st.get("url") or (orig_act.url if orig_act else None)
                val_tmpl = st.get("value_template") or (orig_act.value if orig_act else None)
                param_refs = st.get("parameter_references") or []

                # Remove any emoji characters from step title
                step_title = re.sub(r"[^\x00-\x7F]+", "", step_title).strip() or step_title

                selector_bundle = None
                if orig_act and orig_act.selector_bundle and isinstance(orig_act.selector_bundle, dict):
                    try:
                        selector_bundle = SelectorBundleSchema(**orig_act.selector_bundle)
                    except Exception:
                        selector_bundle = None

                preconds: List[ConditionSchema] = []
                postconds: List[ConditionSchema] = []
                if action_type == "browser_navigate" and url:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc
                    if domain:
                        postconds.append(ConditionSchema(check_type="url_contains", target=domain))

                if selector_bundle and action_type in ("browser_click", "browser_type"):
                    best_sel = (
                        selector_bundle.testId
                        or selector_bundle.ariaLabel
                        or selector_bundle.id
                        or selector_bundle.cssPath
                    )
                    if best_sel:
                        preconds.append(ConditionSchema(check_type="element_visible", target=best_sel))

                compiled_step = CompiledStepSchema(
                    step_id=orig_act.step_id if orig_act else f"step-{uuid.uuid4().hex[:6]}",
                    title=step_title,
                    action_type=action_type,
                    execution_engine=exec_engine,
                    target_app=orig_act.target_app if orig_act else None,
                    url=url,
                    selector_bundle=selector_bundle,
                    value_template=val_tmpl,
                    parameter_references=param_refs,
                    is_idempotent=action_type in ("browser_navigate", "desktop_focus", "browser_press"),
                    preconditions=preconds,
                    postconditions=postconds,
                    metadata=orig_act.metadata if orig_act else {},
                )
                compiled_steps.append(compiled_step)

            # Parameters schema
            params_schema: List[ParameterDefinition] = []
            for p in parsed.get("parameters_schema", []):
                p_name = p.get("name", "").strip()
                if p_name:
                    p_type = p.get("type", "string")
                    if p_type not in ("string", "date", "number", "filepath", "email"):
                        p_type = "string"
                    params_schema.append(
                        ParameterDefinition(
                            name=p_name,
                            type=p_type,
                            description=p.get("description", f"Parameter {p_name}"),
                            required=p.get("required", True),
                            default_value=None if p.get("required", True) else p.get("default_value"),
                        )
                    )

            # Target sites
            target_sites = parsed.get("target_sites", [])
            clean_sites = []
            noise_hosts = {"meet.google.com", "chrome://newtab", "about:blank"}
            for site in target_sites:
                clean_s = site.lower().strip()
                if clean_s.startswith("www."):
                    clean_s = clean_s[4:]
                if clean_s and (clean_s not in noise_hosts or len(target_sites) == 1):
                    if clean_s not in clean_sites:
                        clean_sites.append(clean_s)

            # Clean trigger phrases (NO EMOJIS, no noise site phrases)
            raw_triggers = parsed.get("trigger_phrases", [])
            clean_triggers = []
            for tr in raw_triggers:
                tr_clean = re.sub(r"[^\x00-\x7F]+", "", tr).strip()
                tr_clean = tr_clean.strip("\"'").strip()
                if tr_clean and "on meet" not in tr_clean.lower() and tr_clean not in clean_triggers:
                    clean_triggers.append(tr_clean)

            if not clean_triggers:
                base = (skill_name or prompt_intent or "Automated Task").strip().lower()
                clean_triggers.append(base)

            wf_preconditions: List[ConditionSchema] = []
            primary_site = clean_sites[0] if clean_sites else None
            if primary_site:
                wf_preconditions.append(ConditionSchema(check_type="url_contains", target=primary_site))

            skill_title = parsed.get("name") or skill_name or (prompt_intent.title() if prompt_intent else "Learned Skill")
            skill_title = re.sub(r"[^\x00-\x7F]+", "", skill_title).strip() or skill_title

            desc = parsed.get("description") or f"Dynamic automated workflow for {skill_title}"
            desc = re.sub(r"[^\x00-\x7F]+", "", desc).strip() or desc

            all_engines = {s.execution_engine for s in compiled_steps}
            env = "mixed" if len(all_engines) > 1 else ("desktop" if "desktop" in all_engines else "browser")

            logger.info(
                "AI Distillation succeeded: %d raw actions distilled into %d essential steps with %d dynamic parameters.",
                len(raw_actions),
                len(compiled_steps),
                len(params_schema),
            )

            return CompiledSkillDraft(
                name=skill_title[:255],
                description=desc,
                category=parsed.get("category", category),
                environment=env,
                trigger_phrases=clean_triggers,
                parameters_schema=params_schema,
                steps=compiled_steps,
                preconditions=wf_preconditions,
                target_sites=clean_sites,
                metadata={
                    "distilled_by_ai": True,
                    "target_sites": clean_sites,
                    "primary_site": primary_site,
                    "raw_steps_count": len(raw_actions),
                    "distilled_steps_count": len(compiled_steps),
                },
            )

        except Exception as exc:
            logger.warning("AI distillation failed or timed out (%s), falling back to heuristic compiler.", exc)
            return self.compile(raw_actions, prompt_intent, skill_name, category)

    def compile_skill(self, *args, **kwargs) -> CompiledSkillDraft:
        if "actions" in kwargs:
            kwargs["raw_actions"] = kwargs.pop("actions")
        return self.compile(*args, **kwargs)


compiler = SkillCompiler()


