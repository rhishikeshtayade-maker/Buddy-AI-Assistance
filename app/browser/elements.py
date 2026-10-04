"""BUDDY Browser Target Identification and Confidence Resolution.

Implements layered element identification combining accessibility semantics,
stable attributes, visible text, and scoped selectors with confidence scoring
and page-fingerprint staleness enforcement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.browser.exceptions import (
    AmbiguousTargetError,
    LowConfidenceTargetError,
    StaleTargetError,
)
from app.browser.models import BrowserTarget

logger = logging.getLogger("buddy.browser.elements")


class TargetResolver:
    """Discovers, scores, and validates browser interaction targets."""

    def __init__(self, min_confidence: float = 0.85) -> None:
        self._min_confidence = min_confidence

    def resolve_target(
        self,
        candidate_matches: List[Dict[str, Any]],
        page_url: str,
        current_fingerprint: str,
        query: Optional[str] = None,
    ) -> BrowserTarget:
        """Score candidate element matches and resolve the highest-confidence unambiguous target."""
        if not candidate_matches:
            raise LowConfidenceTargetError(f"No matching element found for query '{query}'.")

        scored_targets: List[BrowserTarget] = []

        for candidate in candidate_matches:
            target_id = candidate.get("target_id") or candidate.get("id") or candidate.get("selector") or "elem"
            role = candidate.get("role")
            accessible_name = candidate.get("accessible_name") or candidate.get("name")
            text = candidate.get("text")
            selector = candidate.get("selector")
            bounding_box = candidate.get("bounding_box")
            target_type = candidate.get("target_type", "element")

            # Layered confidence calculation
            confidence = 0.50

            # 1. Accessible Role + Accessible Name (Gold standard)
            if role and accessible_name:
                confidence = max(confidence, 0.95)

            # 2. Stable unique attribute (id, data-testid)
            raw_id = candidate.get("id")
            if raw_id and not raw_id.startswith("ember") and not raw_id.startswith(":r"):
                confidence = max(confidence, 0.95)

            # 3. Exact semantic text match
            if text and query and text.strip().lower() == query.strip().lower():
                confidence = max(confidence, 0.90)
            elif text and query and query.strip().lower() in text.strip().lower():
                confidence = max(confidence, 0.85)

            # 4. Scoped CSS selector
            if selector and not selector.startswith("html > body"):
                confidence = max(confidence, 0.85)

            target = BrowserTarget(
                target_id=str(target_id),
                selector=selector,
                role=role,
                accessible_name=accessible_name,
                text=text,
                bounding_box=bounding_box,
                page_url=page_url,
                page_fingerprint=current_fingerprint,
                confidence=confidence,
                target_type=target_type,
            )
            scored_targets.append(target)

        # Sort by confidence descending
        scored_targets.sort(key=lambda t: t.confidence, reverse=True)
        best = scored_targets[0]

        # Check confidence threshold
        if best.confidence < self._min_confidence:
            raise LowConfidenceTargetError(
                f"Best target '{best.target_id}' confidence {best.confidence:.2f} is below required threshold {self._min_confidence:.2f}."
            )

        # Ambiguity check: if multiple candidates share the exact top confidence score and have identical role/text
        if len(scored_targets) > 1:
            second = scored_targets[1]
            if (
                abs(best.confidence - second.confidence) < 0.01
                and best.role == second.role
                and best.accessible_name == second.accessible_name
                and best.text == second.text
            ):
                raise AmbiguousTargetError(
                    f"Ambiguous target matches for query '{query}': multiple elements with identical role and name."
                )

        return best

    def validate_target_staleness(
        self,
        target: BrowserTarget,
        current_fingerprint: str,
        current_url: str,
    ) -> None:
        """Verify that a target has not become stale due to page mutation or navigation."""
        if target.page_fingerprint != current_fingerprint:
            raise StaleTargetError(
                f"Target '{target.target_id}' is stale: page fingerprint changed from "
                f"'{target.page_fingerprint}' to '{current_fingerprint}'."
            )

        # Check URL domain/origin consistency (ignoring trailing slash and case)
        target_clean = target.page_url.split("#")[0].rstrip("/").lower()
        current_clean = current_url.split("#")[0].rstrip("/").lower()
        if target_clean != current_clean:
            raise StaleTargetError(
                f"Target '{target.target_id}' belongs to URL '{target.page_url}', but active page is '{current_url}'."
            )
