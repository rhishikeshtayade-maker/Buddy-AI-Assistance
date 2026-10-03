"""BUDDY Core State Machine.

Provides a strongly typed state system, explicit transition rules,
transition validation, event emission, and concurrent-safe state tracking.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from app.core.exceptions import StateTransitionError


class BuddyState(str, Enum):
    """Strongly typed application states for BUDDY."""

    STARTING = "STARTING"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    SHUTTING_DOWN = "SHUTTING_DOWN"


# Explicit transition matrix: current_state -> set of allowed next_states
VALID_TRANSITIONS: Dict[BuddyState, Set[BuddyState]] = {
    BuddyState.STARTING: {
        BuddyState.IDLE,
        BuddyState.ERROR,
    },
    BuddyState.IDLE: {
        BuddyState.LISTENING,
        BuddyState.THINKING,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.LISTENING: {
        BuddyState.THINKING,
        BuddyState.ERROR,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.THINKING: {
        BuddyState.EXECUTING,
        BuddyState.SPEAKING,
        BuddyState.ERROR,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.EXECUTING: {
        BuddyState.THINKING,
        BuddyState.SPEAKING,
        BuddyState.ERROR,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.SPEAKING: {
        BuddyState.IDLE,
        BuddyState.ERROR,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.ERROR: {
        BuddyState.IDLE,
        BuddyState.SHUTTING_DOWN,
    },
    BuddyState.SHUTTING_DOWN: set(),  # Terminal state: no outbound transitions
}


@dataclass(frozen=True)
class StateTransitionRecord:
    """Immutable audit entry for a state transition."""

    previous_state: BuddyState
    new_state: BuddyState
    timestamp: float
    reason: str


class StateMachine:
    """Thread-safe state machine validating and executing BUDDY state transitions."""

    def __init__(
        self,
        initial_state: BuddyState = BuddyState.STARTING,
        on_transition: Optional[Callable[[BuddyState, BuddyState, str, float], Any]] = None,
    ) -> None:
        self._state: BuddyState = initial_state
        self._lock = threading.RLock()
        self._history: List[StateTransitionRecord] = []
        self._on_transition = on_transition

    @property
    def current_state(self) -> BuddyState:
        """Return the current state."""
        with self._lock:
            return self._state

    @property
    def state(self) -> BuddyState:
        """Alias for current_state."""
        return self.current_state

    @property
    def is_terminal(self) -> bool:
        """Check if current state is terminal (SHUTTING_DOWN)."""
        with self._lock:
            return len(VALID_TRANSITIONS.get(self._state, set())) == 0

    @property
    def history(self) -> List[StateTransitionRecord]:
        """Return a copy of all transition history records."""
        with self._lock:
            return list(self._history)

    def set_transition_callback(
        self, callback: Optional[Callable[[BuddyState, BuddyState, str, float], Any]]
    ) -> None:
        """Configure an external callback triggered on each successful transition."""
        with self._lock:
            self._on_transition = callback

    def can_transition_to(self, target_state: BuddyState) -> bool:
        """Check whether a transition to target_state is permitted from current state."""
        with self._lock:
            allowed = VALID_TRANSITIONS.get(self._state, set())
            return target_state in allowed

    def transition_to(
        self,
        target_state: BuddyState,
        reason: str = "Unspecified transition",
    ) -> StateTransitionRecord:
        """Attempt to transition to target_state.

        Raises StateTransitionError if the transition is prohibited.
        Never silently repairs an invalid transition.
        """
        with self._lock:
            if not self.can_transition_to(target_state):
                raise StateTransitionError(
                    from_state=self._state.value,
                    to_state=target_state.value,
                    message=(
                        f"Cannot transition from {self._state.value} to "
                        f"{target_state.value}. Allowed: "
                        f"{[s.value for s in VALID_TRANSITIONS.get(self._state, set())]}"
                    ),
                    details={"reason": reason},
                )

            prev_state = self._state
            self._state = target_state
            record = StateTransitionRecord(
                previous_state=prev_state,
                new_state=target_state,
                timestamp=time.time(),
                reason=reason,
            )
            self._history.append(record)

            if self._on_transition is not None:
                try:
                    self._on_transition(
                        prev_state,
                        target_state,
                        reason,
                        record.timestamp,
                    )
                except Exception:
                    # Exception isolation: failure in external callback must not corrupt state
                    pass

            return record
