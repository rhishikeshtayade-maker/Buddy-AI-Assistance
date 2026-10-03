"""Unit tests for BUDDY Structured Logging and Secret Redaction."""

import io
import logging
import unittest
from app.core import (
    BuddyLogFormatter,
    SecretRedactionFilter,
    get_logger,
    redact_string,
    setup_logging,
    REDACTED_MASK,
)


class TestLoggingAndRedaction(unittest.TestCase):
    """Test suite verifying structured logging output and regex secret scrubbing."""

    def test_redact_string_api_keys(self) -> None:
        """Verify API keys like sk-... are masked."""
        raw = "Connecting with key sk-1234567890abcdef123456 to service"
        scrubbed = redact_string(raw)
        self.assertNotIn("sk-1234567890abcdef123456", scrubbed)
        self.assertIn("sk-1234" + REDACTED_MASK, scrubbed)

    def test_redact_string_password_and_tokens(self) -> None:
        """Verify password, token, pin, and secret pairs are scrubbed."""
        samples = [
            ("password=SuperSecretPassword123!", "password=" + REDACTED_MASK),
            ("secret: 'my-top-secret-val'", "secret=" + REDACTED_MASK),
            ("token: super_secret_token_abc", "token=" + REDACTED_MASK),
            ("pin: 1234", "pin=" + REDACTED_MASK),
            ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6", "Bearer " + REDACTED_MASK),
        ]
        for raw, expected_substr in samples:
            scrubbed = redact_string(raw)
            self.assertIn(REDACTED_MASK, scrubbed, f"Failed for {raw}")

    def test_secret_redaction_logging_filter(self) -> None:
        """Verify log records passing through SecretRedactionFilter are redacted."""
        record = logging.LogRecord(
            name="buddy.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User login attempted with password=MySecretPassword99!",
            args=(),
            exc_info=None,
        )
        redaction_filter = SecretRedactionFilter()
        redaction_filter.filter(record)
        self.assertNotIn("MySecretPassword99!", record.msg)
        self.assertIn(REDACTED_MASK, record.msg)

    def test_structured_log_formatter_with_context(self) -> None:
        """Verify BuddyLogFormatter appends state, event, and op context."""
        formatter = BuddyLogFormatter()
        record = logging.LogRecord(
            name="buddy.agent",
            level=logging.INFO,
            pathname=__file__,
            lineno=20,
            msg="Step executed successfully",
            args=(),
            exc_info=None,
        )
        record.state = "EXECUTING"
        record.event = "StateChangedEvent"
        record.operation = "run_tool"

        formatted = formatter.format(record)
        self.assertIn("[INFO]", formatted)
        self.assertIn("[buddy.agent]", formatted)
        self.assertIn("Step executed successfully", formatted)
        self.assertIn("state=EXECUTING", formatted)
        self.assertIn("event=StateChangedEvent", formatted)
        self.assertIn("op=run_tool", formatted)

    def test_setup_logging_stream_redaction(self) -> None:
        """Verify that logs written to an initialized stream scrub secrets."""
        stream = io.StringIO()
        logger = setup_logging(log_level="DEBUG", stream=stream)
        child = get_logger("test.subsystem")

        child.info("Configured with api_key='sk-abcdef1234567890'")
        output = stream.getvalue()

        self.assertIn("[INFO]", output)
        self.assertNotIn("sk-abcdef1234567890", output)
        self.assertIn(REDACTED_MASK, output)


if __name__ == "__main__":
    unittest.main()
