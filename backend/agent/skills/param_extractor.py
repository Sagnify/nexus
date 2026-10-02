"""
Intelligent Parameter Extraction for Skills.
Extracts parameter values from user prompts using pattern matching and NLP.
Priority: Extract from prompt first, then ask user for missing values.
"""
import json
import logging
import math
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.skills.param_extractor")


class ParameterExtractor:
    """Extract parameter values from user prompts intelligently."""

    EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    DATE_PATTERNS = [
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{4}\b",
    ]
    PHONE_PATTERN = r"(?<!\d)(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}(?!\d)"
    URL_PATTERN = r"https?://[^\s]+"
    NUMBER_PATTERN = r"\b\d+(?:\.\d+)?\b"

    _compiled_patterns = {}

    @classmethod
    def _get_compiled_pattern(cls, pattern: str) -> re.Pattern:
        """Get or compile a regex pattern."""
        if pattern not in cls._compiled_patterns:
            cls._compiled_patterns[pattern] = re.compile(pattern, re.IGNORECASE)
        return cls._compiled_patterns[pattern]

    @staticmethod
    def extract_email(prompt: str) -> Optional[str]:
        """Extract email address from prompt."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(ParameterExtractor.EMAIL_PATTERN, prompt)
            return match.group(0) if match else None
        except Exception as e:
            logger.warning(f"Error extracting email: {e}")
            return None

    @staticmethod
    def extract_emails(prompt: str) -> List[str]:
        """Extract all email addresses from prompt."""
        if not prompt or not isinstance(prompt, str):
            return []
        try:
            return re.findall(ParameterExtractor.EMAIL_PATTERN, prompt)
        except Exception as e:
            logger.warning(f"Error extracting emails: {e}")
            return []

    @staticmethod
    def extract_email_for_parameter(prompt: str, parameter_name: str) -> Optional[str]:
        """Prefer the email address explicitly associated with a recipient role."""
        if not prompt or not isinstance(prompt, str):
            return None
        name_tokens = set(re.findall(r"[a-z0-9]+", parameter_name.lower()))
        role = "bcc" if "bcc" in name_tokens else "cc" if "cc" in name_tokens else None
        if role:
            match = re.search(
                rf"\b{role}\b\s*(?:to\s*)?(?:[:=]\s*)?({ParameterExtractor.EMAIL_PATTERN})",
                prompt,
                re.IGNORECASE,
            )
            return match.group(1) if match else None

        addresses = list(re.finditer(ParameterExtractor.EMAIL_PATTERN, prompt, re.IGNORECASE))
        recipient_match = re.search(
            rf"\b(?:to|recipient)\s*(?:[:=]\s*)?({ParameterExtractor.EMAIL_PATTERN})",
            prompt,
            re.IGNORECASE,
        )
        if recipient_match:
            return recipient_match.group(1)

        if re.search(r"\b(?:to|recipient)\b", prompt, re.IGNORECASE):
            labeled_role_addresses = set()
            for other_role in ("cc", "bcc"):
                role_match = re.search(
                    rf"\b{other_role}\b\s*(?:to\s*)?(?:[:=]\s*)?({ParameterExtractor.EMAIL_PATTERN})",
                    prompt,
                    re.IGNORECASE,
                )
                if role_match:
                    labeled_role_addresses.add(role_match.group(1).lower())
            candidates = [match.group(0) for match in addresses if match.group(0).lower() not in labeled_role_addresses]
            return candidates[0] if candidates else None

        return addresses[0].group(0) if addresses else None

    @staticmethod
    def extract_date(prompt: str) -> Optional[str]:
        """Extract date from prompt."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            for pattern in ParameterExtractor.DATE_PATTERNS:
                match = re.search(pattern, prompt, re.IGNORECASE)
                if match:
                    return match.group(0)
            return None
        except Exception as e:
            logger.warning(f"Error extracting date: {e}")
            return None

    @staticmethod
    def extract_phone(prompt: str) -> Optional[str]:
        """Extract phone number from prompt."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(ParameterExtractor.PHONE_PATTERN, prompt)
            return match.group(0) if match else None
        except Exception as e:
            logger.warning(f"Error extracting phone: {e}")
            return None

    @staticmethod
    def extract_url(prompt: str) -> Optional[str]:
        """Extract URL from prompt."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(ParameterExtractor.URL_PATTERN, prompt)
            return match.group(0).rstrip(".,;:!") if match else None
        except Exception as e:
            logger.warning(f"Error extracting URL: {e}")
            return None

    @staticmethod
    def extract_number(prompt: str, parameter_name: Optional[str] = None) -> Optional[str]:
        """Extract a number, preferring a value labeled for the parameter."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            name = (parameter_name or "").lower()
            if "amount" in name:
                labels = r"amount|total|price"
            elif "count" in name:
                labels = r"count|number\s+of"
            elif name:
                labels = re.escape(name.replace("_", " "))
            else:
                labels = ""
            if labels:
                labeled_match = re.search(
                    rf"\b(?:{labels})\b\s*(?:is\s+|of\s+|[:=]\s*)?(?:[$€£]\s*)?(-?\d+(?:\.\d+)?)",
                    prompt,
                    re.IGNORECASE,
                )
                if labeled_match:
                    return labeled_match.group(1)
            match = re.search(ParameterExtractor.NUMBER_PATTERN, prompt)
            return match.group(0) if match else None
        except Exception as e:
            logger.warning(f"Error extracting number: {e}")
            return None

    @staticmethod
    def extract_quoted_text(prompt: str, quote_char: str = '"') -> Optional[str]:
        """Extract text within quotes."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            pattern = f'{re.escape(quote_char)}([^{re.escape(quote_char)}]+){re.escape(quote_char)}'
            match = re.search(pattern, prompt)
            return match.group(1) if match else None
        except Exception as e:
            logger.warning(f"Error extracting quoted text: {e}")
            return None

    @staticmethod
    def extract_subject_line(prompt: str) -> Optional[str]:
        """Extract email subject from patterns like 'subject: Meeting Update'."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(
                r"\b(?:with\s+subject|subject|regarding|about)\s*:?\s*(?:['\"]([^'\"\\n]+)['\"]|([^,;\n]+?))(?=\s+(?:body|message|saying|and|with)\b|$)",
                prompt,
                re.IGNORECASE
            )
            if match:
                return (match.group(1) or match.group(2) or "").strip().strip("'\"")
            return None
        except Exception as e:
            logger.warning(f"Error extracting subject line: {e}")
            return None

    @staticmethod
    def extract_body_text(prompt: str) -> Optional[str]:
        """Extract email body from patterns like 'body: <text>' or 'saying <text>'."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(r"\b(?:body|message|saying|content|text)\s*:?\s*(.+)$", prompt, re.IGNORECASE)
            if match:
                body = match.group(1).strip()
                body = re.split(
                    r"\s+(?:and\s+)?(?:subject|regarding|about|cc|bcc)\b",
                    body,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip()
                if len(body) >= 2 and body[0] in "\"'" and body[-1] == body[0]:
                    body = body[1:-1]
                return body or None
            return None
        except Exception as e:
            logger.warning(f"Error extracting body text: {e}")
            return None

    @staticmethod
    def extract_search_query(prompt: str) -> Optional[str]:
        """Extract search query from patterns like 'search for <query>'."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            match = re.search(
                r"\b(?:search\s+for|find|lookup|search|google)\s+(?:for\s+)?['\"]?(.+?)(?:['\"]|\s+(?:on|in|at)\s+(?:youtube|google|bing|the web|the internet))?\s*$",
                prompt,
                re.IGNORECASE
            )
            if match:
                query = match.group(1).strip()
                query = re.sub(r"\s+(?:on|in|at)\s+(?:youtube|google|bing|the web|the internet)$", "", query, flags=re.IGNORECASE)
                return query.strip()
            return None
        except Exception as e:
            logger.warning(f"Error extracting search query: {e}")
            return None

    @staticmethod
    def extract_recipient(prompt: str) -> Optional[str]:
        """Extract recipient from patterns like 'to <name/email>'."""
        if not prompt or not isinstance(prompt, str):
            return None
        try:
            email = ParameterExtractor.extract_email(prompt)
            if email:
                return email

            match = re.search(
                r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Z|a-z]{2,})\b",
                prompt,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)

            return None
        except Exception as e:
            logger.warning(f"Error extracting recipient: {e}")
            return None

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format."""
        if not email or not isinstance(email, str):
            return False
        try:
            return bool(re.fullmatch(ParameterExtractor.EMAIL_PATTERN, email))
        except Exception:
            return False

    @staticmethod
    def validate_date(date_str: str) -> bool:
        """Validate date format."""
        if not date_str or not isinstance(date_str, str):
            return False
        formats = ("%B %Y", "%b %Y", "%Y-%m-%d", "%m/%d/%Y", "%Y")
        for date_format in formats:
            try:
                datetime.strptime(date_str.strip(), date_format)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def validate_number(num_str: str) -> bool:
        """Validate number format."""
        if not num_str or not isinstance(num_str, str):
            return False
        try:
            return math.isfinite(float(num_str))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def extract_explicit_parameter(prompt: str, name: str) -> Optional[str]:
        """Extract a named value line, such as ``recipient_email: \"a@b.com\"``."""
        if not prompt or not name:
            return None
        pattern = rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$"
        for line in prompt.splitlines():
            match = re.match(pattern, line, re.IGNORECASE)
            if not match:
                continue
            raw_value = match.group(1)
            try:
                value = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                value = raw_value.strip().strip("\"'")
            if isinstance(value, (str, int, float)) and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def extract_parameters_from_prompt(
        prompt: str,
        parameter_schema: List[Dict],
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Extract parameter values from user prompt based on parameter schema.
        Returns (resolved_params, missing_required_params).
        """
        resolved = {}
        missing = []

        if not prompt or not isinstance(prompt, str):
            logger.warning("Invalid prompt provided")
            prompt = ""

        if not parameter_schema or not isinstance(parameter_schema, list):
            logger.warning("Invalid parameter_schema provided")
            return resolved, missing

        for param in parameter_schema:
            if not isinstance(param, dict):
                logger.warning(f"Invalid parameter structure: {param}")
                continue

            p_name = param.get("name", "").strip().lower()
            if not p_name:
                logger.warning("Parameter missing 'name' field")
                continue

            p_type = param.get("type", "string").lower()
            is_required = param.get("required", True)
            default_val = param.get("default_value")

            found_val = None

            try:
                explicit_val = ParameterExtractor.extract_explicit_parameter(prompt, p_name)
                if explicit_val is not None:
                    found_val = explicit_val
                    if (p_type == "email" or "email" in p_name) and not ParameterExtractor.validate_email(found_val):
                        found_val = None
                    elif (p_type == "number" or "amount" in p_name or "count" in p_name) and not ParameterExtractor.validate_number(found_val):
                        found_val = None
                    elif (p_type == "date" or "date" in p_name or "month" in p_name) and not ParameterExtractor.validate_date(found_val):
                        found_val = None

                elif p_type == "email" or "email" in p_name:
                    found_val = ParameterExtractor.extract_email_for_parameter(prompt, p_name)
                    if found_val and not ParameterExtractor.validate_email(found_val):
                        logger.warning(f"Extracted invalid email: {found_val}")
                        found_val = None

                elif p_type == "date" or "date" in p_name or "month" in p_name:
                    found_val = ParameterExtractor.extract_date(prompt)
                    if found_val and not ParameterExtractor.validate_date(found_val):
                        logger.warning(f"Extracted invalid date: {found_val}")
                        found_val = None

                elif p_type == "phone" or "phone" in p_name:
                    found_val = ParameterExtractor.extract_phone(prompt)

                elif p_type == "url" or "url" in p_name or "link" in p_name:
                    found_val = ParameterExtractor.extract_url(prompt)

                elif p_type == "number" or "amount" in p_name or "count" in p_name:
                    found_val = ParameterExtractor.extract_number(prompt, p_name)
                    if found_val and not ParameterExtractor.validate_number(found_val):
                        logger.warning(f"Extracted invalid number: {found_val}")
                        found_val = None

                elif "subject" in p_name or "title" in p_name:
                    found_val = ParameterExtractor.extract_subject_line(prompt)

                elif "body" in p_name or "message" in p_name or "content" in p_name:
                    found_val = ParameterExtractor.extract_body_text(prompt)

                elif "query" in p_name or "search" in p_name:
                    found_val = ParameterExtractor.extract_search_query(prompt)

                elif "recipient" in p_name or "to" in p_name:
                    found_val = ParameterExtractor.extract_recipient(prompt)

                elif p_type == "string" and not found_val:
                    found_val = ParameterExtractor.extract_quoted_text(prompt)

            except Exception as e:
                logger.error(f"Error extracting parameter '{p_name}': {e}")
                found_val = None

            if not found_val and default_val and not is_required:
                found_val = default_val
                logger.debug(f"Using default value for parameter '{p_name}': {default_val}")

            if found_val:
                resolved[param.get("name", p_name)] = str(found_val)
                logger.debug(f"Extracted parameter '{p_name}': {found_val}")
            elif is_required:
                missing.append(param.get("name", p_name))
                logger.debug(f"Parameter '{p_name}' marked as missing")

        logger.info(f"Parameter extraction complete: {len(resolved)} resolved, {len(missing)} missing")
        return resolved, missing

    @staticmethod
    async def synthesize_parameters_with_ai(
        user_prompt: str,
        skill_name: str,
        parameters_needed: list[str],
        timeout: float = 4.0,
    ) -> dict[str, str]:
        """
        Uses fast LLM reasoning to extract, resolve, and creatively compose missing
        parameters (such as email subject, message body, search query, or recipient)
        from natural language instructions, eliminating unnecessary ask_user pauses.
        """
        if not user_prompt or not parameters_needed:
            return {}

        try:
            import json
            import re
            import asyncio
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch
            from langchain_core.messages import SystemMessage, HumanMessage

            sys_prompt = (
                "You are NEXUS Parameter Synthesizer. A user wants to execute an automated skill.\n"
                "Extract, resolve, and intelligently compose the required parameter values from the user's natural language request.\n"
                "- If an email, username, URL, or explicit value is mentioned in the prompt, extract it.\n"
                "- If a subject, message, content, or body is requested or described (e.g., 'greeting that person and asking how is everything family'), "
                "compose an authentic, polite, well-written subject line and full body text matching the user's instructions.\n"
                "- If a search query or topic is described, formulate the optimal concise search query.\n"
                "Output ONLY a valid JSON dictionary mapping each parameter name to its resolved/composed string value."
            )
            user_msg = (
                f"User Request: \"{user_prompt}\"\n"
                f"Skill Name: \"{skill_name}\"\n"
                f"Parameters To Resolve: {json.dumps(parameters_needed)}"
            )

            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [SystemMessage(content=sys_prompt), HumanMessage(content=user_msg)],
                    operation="fast",
                    temperature=0.2,
                ),
                timeout=timeout,
            )
            content = res.content if hasattr(res, "content") else str(res)
            cleaned = content.strip()
            if "```" in cleaned:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
                if m:
                    cleaned = m.group(1).strip()

            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items() if v is not None and str(v).strip()}
        except Exception as e:
            logger.warning(f"[ParamExtractor] AI parameter synthesis skipped: {e}")

        return {}


extractor = ParameterExtractor()
