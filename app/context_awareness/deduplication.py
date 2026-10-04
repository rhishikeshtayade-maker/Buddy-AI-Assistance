"""BUDDY Deterministic Contextual Deduplication.

Computes unique fingerprints for triggers and suggestions to prevent repetitive spam.
"""

from __future__ import annotations

import hashlib
import time
from typing import Dict, Optional

from app.context_awareness.models import ContextSnapshot, ContextTrigger, TriggerType


class DeduplicationManager:
    """Manages trigger and suggestion deduplication caches with TTL."""

    def __init__(self, time_bucket_seconds: float = 300.0) -> None:
        self.time_bucket_seconds = time_bucket_seconds
        self._seen_fingerprints: Dict[str, float] = {}

    def compute_trigger_fingerprint(
        self,
        trigger: ContextTrigger,
        snapshot: Optional[ContextSnapshot] = None,
    ) -> str:
        """Generate a deterministic fingerprint for a trigger event."""
        # Calculate time bucket
        bucket = int(trigger.timestamp / self.time_bucket_seconds)
        
        # Distill relevant payload key identifiers
        key_id = (
            trigger.payload.get("event", {}).get("event_id")
            or trigger.payload.get("item", {}).get("item_id")
            or trigger.payload.get("notification", {}).get("id")
            or trigger.payload.get("process_name")
            or trigger.source
        )

        app_ident = snapshot.foreground_app.app_identity if snapshot and snapshot.foreground_app else "none"
        raw_str = f"{trigger.trigger_type.value}:{trigger.source}:{key_id}:{app_ident}:{bucket}"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]

    def compute_suggestion_fingerprint(
        self,
        message: str,
        trigger_type: TriggerType,
        target_tool: Optional[str] = None,
    ) -> str:
        """Generate a deterministic fingerprint for a proactive suggestion."""
        now = time.time()
        bucket = int(now / self.time_bucket_seconds)
        raw_str = f"{trigger_type.value}:{message.strip().lower()}:{target_tool or 'none'}:{bucket}"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]

    def is_duplicate(self, fingerprint: str, ttl_seconds: float = 600.0) -> bool:
        """Check if fingerprint was seen within ttl_seconds."""
        now = time.time()
        self._prune(now, ttl_seconds)
        return fingerprint in self._seen_fingerprints

    def record_seen(self, fingerprint: str) -> None:
        """Record fingerprint timestamp."""
        self._seen_fingerprints[fingerprint] = time.time()

    def _prune(self, now: float, ttl_seconds: float) -> None:
        """Prune expired fingerprints."""
        self._seen_fingerprints = {
            fp: ts for fp, ts in self._seen_fingerprints.items() if now - ts < ttl_seconds
        }

    def clear(self) -> None:
        """Clear all deduplication records."""
        self._seen_fingerprints.clear()
