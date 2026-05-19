"""Email validation utilities for WhatsApp booking flow."""
import re
from typing import Optional, Tuple

# Practical RFC-inspired pattern (not full RFC 5322)
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9._%+-]{0,62}[a-zA-Z0-9])?"
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def extract_email_from_text(text: str) -> Optional[str]:
    """
    Extract the first plausible email from free-form WhatsApp text.

    Examples:
        "my email is john@gmail.com" -> john@gmail.com
        "john@gmail.com" -> john@gmail.com
    """
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    # Direct match
    if _EMAIL_RE.match(cleaned):
        return cleaned.lower()
    # Token scan
    for token in re.split(r"[\s,;]+", cleaned):
        token = token.strip().strip("<>").strip("\"'")
        if _EMAIL_RE.match(token):
            return token.lower()
    # Substring search
    match = re.search(
        r"[a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}",
        cleaned,
    )
    if match:
        candidate = match.group(0).lower()
        if _EMAIL_RE.match(candidate):
            return candidate
    return None


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate and normalize an email address.

    Returns:
        (is_valid, normalized_email or None)
    """
    if not email:
        return False, None
    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        return False, None
    if len(normalized) > 254:
        return False, None
    return True, normalized
