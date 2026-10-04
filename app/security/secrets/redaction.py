"""BUDDY Centralized Secret Redaction Subsystem.

Detects and masks sensitive credentials, tokens, keys, passwords, and authorization headers
across log messages, audit trails, memory candidates, tool outputs, and UI displays.

Replacement mask: [REDACTED_SECRET]
Never partial-leaks secrets unnecessarily.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Union

REDACTED_SECRET = "[REDACTED_SECRET]"

# Compiled regex patterns for credential detection
SECRET_PATTERNS: List[re.Pattern] = [
    # 1. API Keys & Specific Provider Tokens
    re.compile(r"\b(sk-[a-zA-Z0-9]{20,T3BlbkFJ[a-zA-Z0-9]{20,})\b", re.IGNORECASE),  # OpenAI legacy
    re.compile(r"\bsk-(?:proj-|none-)?[a-zA-Z0-9_\-]{20,}\b", re.IGNORECASE),          # OpenAI standard
    re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b", re.IGNORECASE),                     # Anthropic
    re.compile(r"\bAIza[0-9A-Za-z\-_]{30,40}\b"),                                     # Google API Key
    re.compile(r"\b(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82})\b"),             # GitHub Personal Access Token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                              # AWS Access Key ID

    # 2. Authorization Headers & Bearer Tokens
    re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[a-zA-Z0-9_\-\.\~]+"),
    re.compile(r"(?i)\bBearer\s+[a-zA-Z0-9_\-\.\~]{16,}\b"),

    # 3. JSON Web Tokens (JWT)
    re.compile(r"\beyJ[a-zA-Z0-9_\-]+\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\b"),

    # 4. Private Cryptographic Keys
    re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
        re.MULTILINE,
    ),

    # 5. Connection Strings & Database URIs with Passwords
    re.compile(r"(?i)\b(?:mongodb|postgres|postgresql|mysql|redis)://[^:]+:([^@]+)@"),

    # 6. Password & Credential Assignment Patterns
    re.compile(r"(?i)\b(?:password|passwd|pwd|client_secret|api_key|secret_key)\s*[:=]\s*['\"]?([^'\"\s\r\n]{4,})['\"]?"),

    # 7. PIN & OTP Patterns
    re.compile(r"(?i)\b(?:pin|otp|passcode)\s*[:=]\s*['\"]?(\d{4,8})['\"]?"),

    # 8. Cookies & Session Identifiers
    re.compile(r"(?i)\b(?:sessionid|connect\.sid|auth_token|session_token)\s*=\s*['\"]?([a-zA-Z0-9_\-\.]{16,})['\"]?"),
]

# Sensitive dictionary keys to deep redact
SENSITIVE_KEY_NAMES: Set[str] = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "credentials",
    "auth",
    "authorization",
    "private_key",
    "secret_key",
    "access_token",
    "refresh_token",
    "master_key",
    "session_token",
    "pin",
    "otp",
}


def redact_string(text: str) -> str:
    """Scrub sensitive patterns from a plaintext string."""
    if not text or not isinstance(text, str):
        return text

    sanitized = text

    # Handle assignment regex with capture groups
    for pattern in SECRET_PATTERNS:
        if pattern.groups > 0:
            # Has a capture group for the sensitive value portion
            def _replace_group(match: re.Match) -> str:
                full = match.group(0)
                captured = match.group(1)
                return full.replace(captured, REDACTED_SECRET)
            sanitized = pattern.sub(_replace_group, sanitized)
        else:
            # Full match replacement
            sanitized = pattern.sub(REDACTED_SECRET, sanitized)

    return sanitized


def redact_structure(data: Any) -> Any:
    """Recursively scrub secrets from nested dictionaries, lists, and primitives."""
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k).lower()
            if any(sens in k_str for sens in SENSITIVE_KEY_NAMES):
                cleaned[k] = REDACTED_SECRET
            else:
                cleaned[k] = redact_structure(v)
        return cleaned

    elif isinstance(data, list):
        return [redact_structure(item) for item in data]

    elif isinstance(data, tuple):
        return tuple(redact_structure(item) for item in data)

    elif isinstance(data, set):
        return {redact_structure(item) for item in data}

    elif isinstance(data, str):
        return redact_string(data)

    return data
