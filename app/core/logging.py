"""BUDDY Centralized Structured Logging & Secret Redaction Subsystem.

Provides thread-safe structured logging, automatic secret redaction,
contextual logging attributes, and standard output formatters.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Dict, Optional

# Regex patterns matching sensitive information to prevent accidental leakage in logs
REDACTION_PATTERNS = [
    # Common API key formats (e.g., sk-..., ak-...)
    re.compile(r"(sk-[a-zA-Z0-9_\-]{16,})", re.IGNORECASE),
    # Key-value secret patterns: key=..., token=..., password=..., secret=...
    re.compile(
        r"(?i)\b(password|secret|api[_-]?key|token|auth[_-]?key|master[_-]?key|pin|credential)"
        r"\s*[:=]\s*['\"]?([^\s'\",&]+)['\"]?"
    ),
    # Authorization header / Bearer token
    re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{12,})"),
    # Generic Private Key Headers
    re.compile(r"-----BEGIN [A-Z0-9_-]+ PRIVATE KEY-----"),
]

REDACTED_MASK = "********"


def redact_string(text: str) -> str:
    """Scrub known secret and token patterns from a string."""
    if not isinstance(text, str):
        return str(text)

    scrubbed = text

    # Mask specific known key patterns
    scrubbed = re.sub(r"(sk-[a-zA-Z0-9_\-]{4})[a-zA-Z0-9_\-]+", r"\1" + REDACTED_MASK, scrubbed)

    # Mask key-value patterns
    def _mask_kv(match: re.Match) -> str:
        prefix = match.group(1)
        return f"{prefix}={REDACTED_MASK}"

    scrubbed = re.sub(
        r"(?i)\b(password|secret|api[_-]?key|token|auth[_-]?key|master[_-]?key|pin|credential)"
        r"\s*[:=]\s*['\"]?([^\s'\",&]+)['\"]?",
        _mask_kv,
        scrubbed,
    )

    # Mask bearer tokens
    scrubbed = re.sub(
        r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{6,})",
        rf"\1{REDACTED_MASK}",
        scrubbed,
    )

    return scrubbed


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets and credentials from all record messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_string(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (redact_string(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    redact_string(a) if isinstance(a, str) else a for a in record.args
                )

        return True


class BuddyLogFormatter(logging.Formatter):
    """Structured formatter attaching timestamp, level, module, message, and context."""

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: str = "%Y-%m-%d %H:%M:%S",
    ) -> None:
        default_fmt = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        super().__init__(fmt or default_fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # Append contextual metadata if present
        context_parts = []
        if hasattr(record, "state") and record.state:
            context_parts.append(f"state={record.state}")
        if hasattr(record, "event") and record.event:
            context_parts.append(f"event={record.event}")
        if hasattr(record, "operation") and record.operation:
            context_parts.append(f"op={record.operation}")

        base_msg = super().format(record)
        if context_parts:
            context_str = " [" + " ".join(context_parts) + "]"
            return f"{base_msg}{context_str}"
        return base_msg


_logging_initialized = False


def setup_logging(
    log_level: str = "INFO",
    stream: Any = sys.stdout,
) -> logging.Logger:
    """Configure structured logging with secret redaction for BUDDY."""
    global _logging_initialized

    level_num = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger("buddy")
    root_logger.setLevel(level_num)

    # Avoid duplicate handlers on re-initialization
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    handler = logging.StreamHandler(stream)
    handler.setLevel(level_num)
    handler.setFormatter(BuddyLogFormatter())
    handler.addFilter(SecretRedactionFilter())

    root_logger.addHandler(handler)
    root_logger.propagate = False
    _logging_initialized = True

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Obtain a namespaced child logger under the 'buddy' hierarchy."""
    if not name.startswith("buddy.") and name != "buddy":
        return logging.getLogger(f"buddy.{name}")
    return logging.getLogger(name)
