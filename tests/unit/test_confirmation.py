"""Unit tests for BUDDY User Confirmation Manager."""

from __future__ import annotations

import time
import unittest

from app.core.exceptions import ConfirmationError
from app.security.confirmation import ConfirmationManager
from app.tools.models import ToolRequest


class TestConfirmation(unittest.TestCase):
    """Verify security invariant enforcement in ConfirmationManager."""

    def setUp(self) -> None:
        self.mgr = ConfirmationManager(default_ttl_seconds=1.0)
        self.request = ToolRequest(
            request_id="req-abc",
            tool_name="file.rename",
            arguments={"source": "a.txt", "destination": "b.txt"},
        )

    def test_confirmation_token_issued_and_verified(self) -> None:
        token_obj = self.mgr.request_confirmation(self.request)
        self.assertTrue(len(token_obj.token) >= 32)

        # Validate with exact matching request, tool, and arguments
        valid = self.mgr.validate_and_consume(
            token=token_obj.token,
            request_id="req-abc",
            tool_name="file.rename",
            arguments={"source": "a.txt", "destination": "b.txt"},
        )
        self.assertTrue(valid)

    def test_replay_attack_rejected(self) -> None:
        token_obj = self.mgr.request_confirmation(self.request)

        # First consumption succeeds
        self.mgr.validate_and_consume(
            token=token_obj.token,
            request_id="req-abc",
            tool_name="file.rename",
            arguments={"source": "a.txt", "destination": "b.txt"},
        )

        # Second consumption with the same token must be rejected (replay)
        with self.assertRaises(ConfirmationError) as ctx:
            self.mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req-abc",
                tool_name="file.rename",
                arguments={"source": "a.txt", "destination": "b.txt"},
            )
        self.assertIn("replay", str(ctx.exception).lower())

    def test_expired_token_rejected(self) -> None:
        # Issue token with very short TTL
        token_obj = self.mgr.request_confirmation(self.request, ttl_seconds=0.05)
        time.sleep(0.1)

        with self.assertRaises(ConfirmationError) as ctx:
            self.mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req-abc",
                tool_name="file.rename",
                arguments={"source": "a.txt", "destination": "b.txt"},
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_argument_tampering_rejected(self) -> None:
        token_obj = self.mgr.request_confirmation(self.request)

        # Attempt to confirm with tampered destination
        tampered_args = {"source": "a.txt", "destination": "important_file.txt"}
        with self.assertRaises(ConfirmationError) as ctx:
            self.mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req-abc",
                tool_name="file.rename",
                arguments=tampered_args,
            )
        self.assertIn("argument mismatch", str(ctx.exception).lower())

    def test_tool_name_tampering_rejected(self) -> None:
        token_obj = self.mgr.request_confirmation(self.request)

        with self.assertRaises(ConfirmationError) as ctx:
            self.mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req-abc",
                tool_name="file.delete",  # Tampered tool
                arguments={"source": "a.txt", "destination": "b.txt"},
            )
        self.assertIn("tool mismatch", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
