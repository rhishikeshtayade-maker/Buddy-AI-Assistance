"""Unit tests for BUDDY State Machine and State Transitions."""

import unittest
from app.core import (
    BuddyState,
    StateMachine,
    StateTransitionError,
    VALID_TRANSITIONS,
)


class TestStateMachine(unittest.TestCase):
    """Test suite verifying strongly typed state machine transitions and safety."""

    def setUp(self) -> None:
        self.sm = StateMachine(BuddyState.STARTING)

    def test_initial_state(self) -> None:
        """Verify initial state is STARTING by default."""
        self.assertEqual(self.sm.current_state, BuddyState.STARTING)
        self.assertEqual(self.sm.state, BuddyState.STARTING)
        self.assertFalse(self.sm.is_terminal)

    def test_valid_transitions_from_starting(self) -> None:
        """STARTING -> IDLE and STARTING -> ERROR are valid."""
        self.assertTrue(self.sm.can_transition_to(BuddyState.IDLE))
        self.assertTrue(self.sm.can_transition_to(BuddyState.ERROR))

        rec = self.sm.transition_to(BuddyState.IDLE, reason="Bootstrap completed")
        self.assertEqual(self.sm.current_state, BuddyState.IDLE)
        self.assertEqual(rec.previous_state, BuddyState.STARTING)
        self.assertEqual(rec.new_state, BuddyState.IDLE)
        self.assertEqual(rec.reason, "Bootstrap completed")

    def test_invalid_transition_rejected(self) -> None:
        """STARTING -> LISTENING is invalid and must raise StateTransitionError."""
        self.assertFalse(self.sm.can_transition_to(BuddyState.LISTENING))
        with self.assertRaises(StateTransitionError) as ctx:
            self.sm.transition_to(BuddyState.LISTENING, reason="Invalid attempt")
        self.assertIn("STARTING", str(ctx.exception))
        self.assertIn("LISTENING", str(ctx.exception))
        # State must not be modified after rejected transition
        self.assertEqual(self.sm.current_state, BuddyState.STARTING)

    def test_full_operational_lifecycle(self) -> None:
        """Test happy path: STARTING -> IDLE -> LISTENING -> THINKING -> EXECUTING -> SPEAKING -> IDLE -> SHUTTING_DOWN."""
        self.sm.transition_to(BuddyState.IDLE, reason="Startup")
        self.sm.transition_to(BuddyState.LISTENING, reason="Wake word heard")
        self.sm.transition_to(BuddyState.THINKING, reason="Audio transcribed")
        self.sm.transition_to(BuddyState.EXECUTING, reason="Action dispatched")
        self.sm.transition_to(BuddyState.SPEAKING, reason="Action completed, voicing answer")
        self.sm.transition_to(BuddyState.IDLE, reason="Speech output finished")
        self.sm.transition_to(BuddyState.SHUTTING_DOWN, reason="User exit")

        self.assertEqual(self.sm.current_state, BuddyState.SHUTTING_DOWN)
        self.assertTrue(self.sm.is_terminal)

    def test_thinking_to_speaking_transition(self) -> None:
        """THINKING -> SPEAKING is permitted for direct answers without tool execution."""
        self.sm.transition_to(BuddyState.IDLE, reason="Startup")
        self.sm.transition_to(BuddyState.THINKING, reason="Text query")
        rec = self.sm.transition_to(BuddyState.SPEAKING, reason="Direct response ready")
        self.assertEqual(rec.new_state, BuddyState.SPEAKING)

    def test_terminal_state_rejects_all_transitions(self) -> None:
        """SHUTTING_DOWN is terminal; no outbound transitions are allowed."""
        self.sm.transition_to(BuddyState.IDLE, reason="Startup")
        self.sm.transition_to(BuddyState.SHUTTING_DOWN, reason="Shutdown")
        self.assertTrue(self.sm.is_terminal)

        for target in BuddyState:
            self.assertFalse(self.sm.can_transition_to(target))
            with self.assertRaises(StateTransitionError):
                self.sm.transition_to(target, reason="Attempted revival")

    def test_error_state_recovery_and_shutdown(self) -> None:
        """ERROR state allows transition back to IDLE (recovery) or SHUTTING_DOWN."""
        self.sm.transition_to(BuddyState.ERROR, reason="Startup error")
        self.assertTrue(self.sm.can_transition_to(BuddyState.IDLE))
        self.assertTrue(self.sm.can_transition_to(BuddyState.SHUTTING_DOWN))
        self.assertFalse(self.sm.can_transition_to(BuddyState.SPEAKING))

        # Recovery to IDLE
        self.sm.transition_to(BuddyState.IDLE, reason="Error cleared")
        self.assertEqual(self.sm.current_state, BuddyState.IDLE)

    def test_transition_callback_and_history(self) -> None:
        """Verify transition callback fires and history preserves sequential records."""
        events_emitted = []

        def callback(prev, new, reason, ts):
            events_emitted.append((prev, new, reason))

        self.sm.set_transition_callback(callback)
        self.sm.transition_to(BuddyState.IDLE, reason="Init")
        self.sm.transition_to(BuddyState.LISTENING, reason="Wake")

        self.assertEqual(len(events_emitted), 2)
        self.assertEqual(events_emitted[0], (BuddyState.STARTING, BuddyState.IDLE, "Init"))
        self.assertEqual(events_emitted[1], (BuddyState.IDLE, BuddyState.LISTENING, "Wake"))

        history = self.sm.history
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].previous_state, BuddyState.STARTING)
        self.assertEqual(history[1].new_state, BuddyState.LISTENING)


if __name__ == "__main__":
    unittest.main()
