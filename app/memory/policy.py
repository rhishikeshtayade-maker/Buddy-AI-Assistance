"""BUDDY Long-Term Memory Policy & Secret Detection Subsystem.

Enforces conservative privacy and security policies:
1. Rejection of passwords, credentials, tokens, API keys, private keys, and OTPs.
2. Neutralization and rejection of prompt injection and security override attempts.
3. Sensitivity categorization and TTL assignment based on memory provenance.
4. Non-negotiable principle: Memory is contextual data, NEVER security authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import re
import time
from typing import List, Optional, Pattern, Tuple

from app.core.config import BuddyConfig
from app.memory.models import MemoryCandidate, MemoryRecord, MemorySensitivity, MemorySource, MemoryType

logger = logging.getLogger("buddy.memory.policy")


class PolicyDecisionType(str, Enum):
    """Evaluation outcome for a candidate memory."""

    ALLOWED = "allowed"
    REJECTED_SECRET = "rejected_secret"
    REJECTED_INJECTION = "rejected_injection"
    REJECTED_EMPTY = "rejected_empty"
    REJECTED_OVERSIZED = "rejected_oversized"


@dataclass(frozen=True)
class PolicyDecision:
    """Detailed verdict produced by MemoryPolicy."""

    decision: PolicyDecisionType
    reason: str
    suggested_type: MemoryType = MemoryType.SEMANTIC
    suggested_sensitivity: MemorySensitivity = MemorySensitivity.PERSONAL
    ttl_seconds: Optional[float] = None
    requires_confirmation: bool = False

    @property
    def is_allowed(self) -> bool:
        return self.decision == PolicyDecisionType.ALLOWED


# Regex patterns for detecting credentials, tokens, and private material
SECRET_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    # API Keys & Specific Formats
    ("openai_api_key", re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE)),
    ("github_token", re.compile(r"gh[pousr]_[a-zA-Z0-9]{20,}", re.IGNORECASE)),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9a-zA-Z-]{20,}", re.IGNORECASE)),
    ("jwt_token", re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")),
    # Private Keys
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----", re.IGNORECASE)),
    # Passwords & Credentials
    ("password_assignment", re.compile(r"(?:password|passwd|pwd)\s*(?:is|[:=])\s*\S+", re.IGNORECASE)),
    ("pin_assignment", re.compile(r"\b(?:pin|pincode)\s*(?:is|[:=])\s*\d{4,8}\b", re.IGNORECASE)),
    ("otp_assignment", re.compile(r"\b(?:otp|one-time\s*password|verification\s*code)\s*(?:is|[:=])\s*\d{4,8}\b", re.IGNORECASE)),
    ("secret_assignment", re.compile(r"(?:api_key|access_token|client_secret|auth_token|session_cookie|cookie|refresh_token|credential)\s*(?:is|[:=])\s*\S+", re.IGNORECASE)),
    # Bearer / Auth Headers
    ("bearer_token", re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE)),
    # Payment Cards (13 to 19 digits)
    ("payment_card", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")),
    # Common Credential Contexts
    ("credential_disclosure", re.compile(r"\bmy (?:password|pin|secret|api key|token) is\b", re.IGNORECASE)),
]

# Prohibited Prompt Injection & Security Override Patterns in Memory
INJECTION_OVERRIDE_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("bypass_confirmation", re.compile(r"\b(?:bypass|skip|disable|ignore)\s+.*confirmations?\b", re.IGNORECASE)),
    ("bypass_permission", re.compile(r"\b(?:bypass|skip|disable|ignore)\s+.*permissions?\b", re.IGNORECASE)),
    ("execute_shell", re.compile(r"\b(?:always|auto)\s+execute\s+.*(?:shell|powershell|cmd|bash)\b", re.IGNORECASE)),
    ("unrestricted_execution", re.compile(r"\b(?:permanently\s+)?authoriz(?:e|ed)\s+.*(?:shell|powershell|cmd|bash|unrestricted|any\s+command)\b", re.IGNORECASE)),
    ("override_safety", re.compile(r"\b(?:ignore|override|disable)\s+.*(?:instructions?|safety|security)\b", re.IGNORECASE)),
]

MAX_MEMORY_CONTENT_CHARS = 4000


class MemoryPolicy:
    """Validates memory records against privacy, security, and persistence policies."""

    def __init__(self, config: Optional[BuddyConfig] = None) -> None:
        self._config = config or BuddyConfig()
        self._secret_detection_enabled = self._config.memory_secret_detection_enabled
        self._require_confirmation = self._config.memory_require_confirmation

    def detect_secrets(self, text: str) -> List[str]:
        """Scan text for any sensitive credentials or secret token patterns."""
        if not self._secret_detection_enabled:
            return []

        detected: List[str] = []
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                detected.append(name)
        return detected

    def detect_security_injections(self, text: str) -> List[str]:
        """Detect attempts to store malicious instructions that try to hijack security controls."""
        detected: List[str] = []
        for name, pattern in INJECTION_OVERRIDE_PATTERNS:
            if pattern.search(text):
                detected.append(name)
        return detected

    def evaluate_candidate(self, candidate: MemoryCandidate) -> PolicyDecision:
        """Evaluate whether a proposed memory candidate should be permitted and persisted."""
        content = candidate.content.strip()

        # 1. Non-empty check
        if not content:
            return PolicyDecision(
                decision=PolicyDecisionType.REJECTED_EMPTY,
                reason="Memory candidate content cannot be empty or whitespace only.",
            )

        # 2. Length check
        if len(content) > MAX_MEMORY_CONTENT_CHARS:
            return PolicyDecision(
                decision=PolicyDecisionType.REJECTED_OVERSIZED,
                reason=f"Memory candidate exceeds maximum allowable length ({MAX_MEMORY_CONTENT_CHARS} characters).",
            )

        # 3. Secret Detection Check (Conservative: False positives preferred over storing secrets)
        detected_secrets = self.detect_secrets(content)
        if detected_secrets:
            logger.warning("Memory candidate rejected: secret pattern detected (%s)", detected_secrets)
            return PolicyDecision(
                decision=PolicyDecisionType.REJECTED_SECRET,
                reason=f"Secret or credential pattern detected ({', '.join(detected_secrets)}). Storing credentials is strictly forbidden.",
                suggested_sensitivity=MemorySensitivity.SECRET,
            )

        # 4. Security Injection & Override Check
        detected_injections = self.detect_security_injections(content)
        if detected_injections:
            logger.warning("Memory candidate rejected: security override attempt detected (%s)", detected_injections)
            return PolicyDecision(
                decision=PolicyDecisionType.REJECTED_INJECTION,
                reason="Memory candidate attempts to override security policies or authorize unrestricted actions. Memory is contextual data, not policy.",
            )

        # 5. Determine Sensitivity & TTL based on MemoryType and Source
        mtype = candidate.memory_type
        source = candidate.source
        now = time.time()
        ttl_seconds: Optional[float] = None
        requires_conf = False

        if mtype == MemoryType.SESSION:
            ttl_seconds = self._config.memory_session_ttl_seconds
            sensitivity = MemorySensitivity.PERSONAL
        elif mtype == MemoryType.EPISODIC:
            ttl_seconds = float(self._config.memory_episodic_ttl_days * 86400)
            sensitivity = MemorySensitivity.PERSONAL
        elif mtype == MemoryType.PROFILE:
            sensitivity = MemorySensitivity.PERSONAL
            if source == MemorySource.AI_INFERRED and self._require_confirmation:
                requires_conf = True
        else:  # SEMANTIC
            sensitivity = MemorySensitivity.PERSONAL
            if source == MemorySource.AI_INFERRED:
                ttl_seconds = float(self._config.memory_inferred_ttl_days * 86400)
                if self._require_confirmation:
                    requires_conf = True

        return PolicyDecision(
            decision=PolicyDecisionType.ALLOWED,
            reason="Content passed privacy, secret detection, and security injection evaluations.",
            suggested_type=mtype,
            suggested_sensitivity=sensitivity,
            ttl_seconds=ttl_seconds,
            requires_confirmation=requires_conf,
        )
