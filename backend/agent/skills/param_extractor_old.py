"""
Intelligent Parameter Extraction for Skills.
Extracts parameter values from user prompts using pattern matching and NLP.
Priority: Extract from prompt first, then ask user for missing values.
"""
import re
from typing import Dict, List, Optional, Tuple


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
    PHONE_PATTERN = r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"
    URL_PATTERN = r"https?://[^\s]+"

    @staticmethod
    def extract_email(prompt: str) -> Optional[str]:
        """Extract email address from prompt."""
        match = re.search(ParameterExtractor.EMAIL_PATTERN, prompt)
        return match.group(0) if match else None

    @staticmethod
    def extract_emails(prompt: str) -> List[str]:
        """Extract all email addresses from prompt."""
        return re.findall(ParameterExtractor.EMAIL_PATTERN, prompt)

    @staticmethod
    def extract_date(prompt: str) -> Optional[str]:
        """Extract date from prompt."""
        for pattern in ParameterExtractor.DATE_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def extract_phone(prompt: str) -> Optional[str]:
        """Extract phone number from prompt."""
        match = re.search(ParameterExtractor.PHONE_PATTERN, prompt)
        return match.group(0) if match else None

    @staticmethod
    def extract_url(prompt: str) -> Optional[str]:
        """Extract URL from prompt."""
        match = re.search(ParameterExtractor.URL_PATTERN, prompt)
        return match.group(0) if match else None

    @staticmethod
    def extract_quoted_text(prompt: str, quote_char: str = '"') -> Optional[str]:
        """Extract text within quotes."""
        pattern = f'{re.escape(quote_char)}([^{re.escape(quote_char)}]+){re.escape(quote_char)}'
        match = re.search(pattern, prompt)
        return match.group(1) if match else None

    @staticmethod
    def extract_subject_line(prompt: str) -> Optional[str]:
        """Extract email subject from patterns like 'subject: Meeting Update' or 'about the meeting'."""
        # Pattern: "subject: <text>" or "with subject <text>"
        match = re.search(
            r"(?:subject|with subject|regarding|about)\s+['\"]?([^'\"\\n,;]+?)(?:['\"]|\\s+(?:body|message|saying|and|with)|$)",
            prompt,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def extract_body_text(prompt: str) -> Optional[str]:
        """Extract email body from patterns like 'body: <text>' or 'saying <text>'."""
        match = re.search(
            r"(?:body|message|saying|content|text)\s+['\"]?(.+?)(?:['\"]|\\s+(?:subject|regarding|about|cc|bcc)|$)",
            prompt,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def extract_search_query(prompt: str) -> Optional[str]:
        """Extract search query from patterns like 'search for <query>' or 'find <query>'."""
        match = re.search(
            r"(?:search for|find|lookup|search|google)\s+['\"]?([^'\"\\n]+?)(?:['\"]|$)",
            prompt,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def extract_recipient(prompt: str) -> Optional[str]:
        """Extract recipient from patterns like 'to <name/email>' or 'send to <email>'."""
        # Try email first
        email = ParameterExtractor.extract_email(prompt)
        if email:
            return email

        # Try "to <Name>" pattern
        match = re.search(r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Z|a-z]{2,})\b", prompt)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def extract_parameters_from_prompt(
        prompt: str,
        parameter_schema: List[Dict],
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Extract parameter values from user prompt based on parameter schema.
        Returns (resolved_params, missing_required_params).

        Priority order:
        1. Extract from prompt using pattern matching
        2. Use default values if available
        3. Mark as missing if required and not found
        """
        resolved = {}
        missing = []

        for param in parameter_schema:
            p_name = param.get("name", "").lower()
            p_type = param.get("type", "string")
            is_required = param.get("required", True)
            default_val = param.get("default_value")

            found_val = None

            # 1. Email extraction
            if p_type == "email" or "email" in p_name or "recipient" in p_name:
                found_val = ParameterExtractor.extract_email(prompt)

            # 2. Date extraction
            elif p_type == "date" or "date" in p_name or "month" in p_name:
                found_val = ParameterExtractor.extract_date(prompt)

            # 3. Phone extraction
            elif p_type == "phone" or "phone" in p_name:
                found_val = ParameterExtractor.extract_phone(prompt)

            # 4. URL extraction
            elif p_type == "url" or "url" in p_name or "link" in p_name:
                found_val = ParameterExtractor.extract_url(prompt)

            # 5. Subject line extraction
            elif "subject" in p_name or "title" in p_name:
                found_val = ParameterExtractor.extract_subject_line(prompt)

            # 6. Body/message extraction
            elif "body" in p_name or "message" in p_name or "content" in p_name:
                found_val = ParameterExtractor.extract_body_text(prompt)

            # 7. Search query extraction
            elif "query" in p_name or "search" in p_name:
                found_val = ParameterExtractor.extract_search_query(prompt)

            # 8. Recipient extraction
            elif "recipient" in p_name or "to" in p_name:
                found_val = ParameterExtractor.extract_recipient(prompt)

            # 9. Generic string extraction from quoted text
            elif p_type == "string" and not found_val:
                found_val = ParameterExtractor.extract_quoted_text(prompt)

            # Use default if not found
            if not found_val and default_val and not is_required:
                found_val = default_val

            # Store or mark as missing
            if found_val:
                resolved[param.get("name", p_name)] = found_val
            elif is_required:
                missing.append(param.get("name", p_name))

        return resolved, missing


extractor = ParameterExtractor()
