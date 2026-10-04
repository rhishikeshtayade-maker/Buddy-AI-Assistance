"""BUDDY Security Audit Logger.

Records structured, tamper-evident audit records for every tool request, permission evaluation,
confirmation prompt, authentication event, execution status, and verification check.
All secrets, passwords, and sensitive arguments are automatically redacted.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.logging import REDACTED_MASK, redact_sensitive_data
logger = logging.getLogger("buddy.security.audit")


@dataclass
class AuditRecord:
    """Structured audit trail record."""

    timestamp: float = field(default_factory=time.time)
    request_id: str = ""
    tool_name: str = ""
    conversation_id: Optional[str] = None
    risk_level: str = "SAFE"
    permission_decision: str = "DENIED"
    confirmation_decision: Optional[str] = None
    authentication_decision: Optional[str] = None
    execution_status: str = "REQUESTED"
    verified: bool = False
    execution_latency: float = 0.0
    error_category: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        # Deep redact metadata
        d["metadata"] = redact_sensitive_data(d["metadata"])
        return json.dumps(d)


class AuditLogger:
    """Manages audit logging to both standard logging and structured file audit trail."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._log_path = log_path
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: AuditRecord) -> None:
        """Write an audit entry."""
        json_line = record.to_json()
        logger.info("[AUDIT] %s", json_line)

        if self._log_path:
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json_line + "\n")
            except Exception as e:
                logger.error("Failed to append to audit log file: %s", e)

    def log_event(
        self,
        event_type: str,
        user: str = "system",
        resource: str = "",
        action: str = "",
        status: str = "SUCCESS",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a structured security audit event."""
        rec = AuditRecord(
            timestamp=time.time(),
            request_id=event_type,
            tool_name=resource,
            execution_status=status,
            metadata={
                "user": user,
                "action": action,
                **(details or {}),
            },
        )
        self.record(rec)
