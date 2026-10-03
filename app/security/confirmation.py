"""BUDDY User Confirmation Manager.

Issues and validates non-transferable, single-use, time-bounded confirmation tokens
tied strictly to exact tool identifiers, request IDs, and invocation arguments.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.exceptions import ConfirmationError
from app.tools.models import ToolRequest

logger = logging.getLogger("buddy.security.confirmation")


def _hash_arguments(arguments: Dict[str, Any]) -> str:
    """Produce a deterministic SHA-256 digest of input arguments."""
    try:
        serialized = json.dumps(arguments, sort_keys=True, default=str)
    except Exception:
        serialized = str(sorted(arguments.items()))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfirmationToken:
    """Cryptographic single-use token binding a confirmation prompt to an exact action."""

    token: str
    request_id: str
    tool_name: str
    arguments_hash: str
    created_at: float
    expires_at: float


class ConfirmationManager:
    """Manages creation, verification, and revocation of interactive user confirmation tokens."""

    def __init__(self, default_ttl_seconds: float = 60.0) -> None:
        self._default_ttl = default_ttl_seconds
        self._tokens: Dict[str, ConfirmationToken] = {}
        self._consumed_tokens: set[str] = set()
        self._lock = threading.RLock()

    def request_confirmation(
        self,
        request: ToolRequest,
        ttl_seconds: Optional[float] = None,
    ) -> ConfirmationToken:
        """Create a new confirmation token bound to the request."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        now = time.time()
        token_str = secrets.token_urlsafe(32)
        arg_hash = _hash_arguments(request.arguments)

        token_obj = ConfirmationToken(
            token=token_str,
            request_id=request.request_id,
            tool_name=request.tool_name,
            arguments_hash=arg_hash,
            created_at=now,
            expires_at=now + ttl,
        )

        with self._lock:
            self._tokens[token_str] = token_obj

        logger.info(
            "Created confirmation token for request '%s' tool '%s' (expires in %.1fs)",
            request.request_id,
            request.tool_name,
            ttl,
        )
        return token_obj

    def validate_and_consume(
        self,
        token: str,
        request_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Validate that token matches request, tool, arguments, is not expired, and not reused.

        Raises:
            ConfirmationError: If token is invalid, expired, mismatched, or replayed.
        """
        now = time.time()

        with self._lock:
            # 1. Replay check
            if token in self._consumed_tokens:
                raise ConfirmationError(f"Confirmation token '{token}' has already been consumed (replay attack rejected).")

            # 2. Existence check
            token_obj = self._tokens.get(token)
            if not token_obj:
                raise ConfirmationError("Invalid or unknown confirmation token.")

            # 3. Expiration check
            if now > token_obj.expires_at:
                del self._tokens[token]
                raise ConfirmationError("Confirmation token has expired.")

            # 4. Request ID binding check
            if token_obj.request_id != request_id:
                raise ConfirmationError(
                    f"Token request ID mismatch: expected '{token_obj.request_id}', got '{request_id}'."
                )

            # 5. Tool binding check
            if token_obj.tool_name != tool_name:
                raise ConfirmationError(
                    f"Token tool mismatch: expected '{token_obj.tool_name}', got '{tool_name}'."
                )

            # 6. Arguments binding check
            expected_arg_hash = _hash_arguments(arguments)
            if token_obj.arguments_hash != expected_arg_hash:
                raise ConfirmationError(
                    "Token argument mismatch: parameters were modified between confirmation request and execution."
                )

            # Consume token
            del self._tokens[token]
            self._consumed_tokens.add(token)

        logger.info("Confirmation token verified and consumed for request '%s'.", request_id)
        return True

    def clear(self) -> None:
        """Clear all active and consumed tokens."""
        with self._lock:
            self._tokens.clear()
            self._consumed_tokens.clear()
