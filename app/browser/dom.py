"""BUDDY Browser DOM Inspection and Fingerprinting.

Extracts DOM structures, interactive elements, forms, and visible text safely.
Computes deterministic page fingerprints and classifies form field sensitivities.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.browser.models import FormField, FormFieldSensitivity

logger = logging.getLogger("buddy.browser.dom")

# Keywords for classifying sensitive input fields
PASSWORD_KEYWORDS = {"password", "pass", "pwd", "passwd", "secret", "api_key", "apikey", "auth", "bearer", "cookie", "session"}
OTP_KEYWORDS = {"otp", "token", "2fa", "mfa", "passcode", "authcode", "verification_code", "security_code", "pin", "session_id"}
PAYMENT_KEYWORDS = {"card", "creditcard", "cardnumber", "cvv", "cvc", "csc", "expmonth", "expyear", "billing"}
PERSONAL_KEYWORDS = {"email", "phone", "telephone", "mobile", "ssn", "socialsecurity", "dob", "birthdate"}
SEARCH_KEYWORDS = {"search", "q", "query", "find", "keyword", "filter"}

CAPTCHA_SIGNATURES = [
    re.compile(r"recaptcha", re.IGNORECASE),
    re.compile(r"hcaptcha", re.IGNORECASE),
    re.compile(r"cf-turnstile", re.IGNORECASE),
    re.compile(r"geetest", re.IGNORECASE),
    re.compile(r"arkose", re.IGNORECASE),
    re.compile(r"captcha", re.IGNORECASE),
]


def classify_input_sensitivity(
    field_id: str,
    name: Optional[str] = None,
    field_type: str = "text",
    placeholder: Optional[str] = None,
    label: Optional[str] = None,
) -> FormFieldSensitivity:
    """Classify the sensitivity level of a form input element."""
    f_type = (field_type or "").lower().strip()
    if f_type == "password":
        return FormFieldSensitivity.CREDENTIAL

    combined_text = " ".join(
        filter(None, [field_id, name, placeholder, label, f_type])
    ).lower()

    # 1. Credential check
    if any(k in combined_text for k in PASSWORD_KEYWORDS):
        return FormFieldSensitivity.CREDENTIAL

    # 2. OTP / MFA check
    if any(k in combined_text for k in OTP_KEYWORDS):
        return FormFieldSensitivity.CREDENTIAL

    # 3. Payment check
    if any(k in combined_text for k in PAYMENT_KEYWORDS):
        return FormFieldSensitivity.PAYMENT

    # 4. Search check (safe)
    if any(k in combined_text for k in SEARCH_KEYWORDS):
        return FormFieldSensitivity.SAFE

    # 5. Personal check
    if any(k in combined_text for k in PERSONAL_KEYWORDS):
        return FormFieldSensitivity.PERSONAL

    return FormFieldSensitivity.SAFE


def compute_page_fingerprint(
    url: str,
    title: str,
    dom_summary: Optional[List[Dict[str, Any]]] = None,
    raw_html: Optional[str] = None,
) -> str:
    """Generate a deterministic structural hash representing current page state.

    The fingerprint changes when meaningful page structure, URL, or interactive elements change.
    """
    hasher = hashlib.sha256()
    hasher.update(url.strip().encode("utf-8"))
    hasher.update(title.strip().encode("utf-8"))

    if dom_summary:
        for node in dom_summary[:200]:
            tag = node.get("tag", "")
            nid = node.get("id", "")
            role = node.get("role", "")
            node_key = f"{tag}:{nid}:{role}"
            hasher.update(node_key.encode("utf-8"))
    elif raw_html:
        # Extract tag names and ids for structural fingerprinting without full content
        tags = re.findall(r"<\s*([a-zA-Z0-9]+)(?:\s+id=[\"']([^\"']+)[\"'])?", raw_html[:10000])
        for tag, nid in tags[:100]:
            hasher.update(f"{tag}:{nid}".encode("utf-8"))

    return hasher.hexdigest()[:16]


def detect_captcha(html_or_dom: str) -> bool:
    """Detect presence of CAPTCHA challenges in page structure."""
    if not html_or_dom:
        return False
    for pat in CAPTCHA_SIGNATURES:
        if pat.search(html_or_dom):
            return True
    return False


def detect_login_form(fields: List[FormField]) -> bool:
    """Detect if current page or form constitutes a login interface."""
    has_credential_field = any(f.sensitivity == FormFieldSensitivity.CREDENTIAL for f in fields)
    has_username_field = any(
        f.field_type in ("text", "email") or "user" in (f.name or "").lower()
        for f in fields
    )
    return has_credential_field and has_username_field
