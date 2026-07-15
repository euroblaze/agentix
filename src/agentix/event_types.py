"""Contract B v2 event types — the agent→control-plane lifecycle stream.

The kernel owns this vocabulary. The cross-cluster wire contract
(``contracts/session-event.schema.json``, locked #430-D) stays the canonical seam;
``tests/unit/test_event_contract_drift.py`` asserts this enum and the schema never
drift, so no generated app package is imported here. Module-level aliases
(`SESSION_STARTED` …) ARE the EventType members — there is no hand-kept list to
drift. The agent must only emit these.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Session-event type (agent → control plane); mirror of the wire schema."""

    SESSION_STARTED = "session_started"
    SESSION_END = "session_end"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    SAFETY_EVENT = "safety_event"
    CHECKPOINT_REQUESTED = "checkpoint_requested"
    VERIFY_STAGE = "verify_stage"


EVENT_TYPES = frozenset(EventType)

# Session lifecycle (the whole run).
SESSION_STARTED = EventType.SESSION_STARTED
SESSION_END = EventType.SESSION_END

# Per-Model boundaries (one Job acts on one Model).
MODEL_STARTED = EventType.MODEL_STARTED
MODEL_COMPLETED = EventType.MODEL_COMPLETED

# Per-Job boundaries (a Session decomposes into N Jobs; emitted by the worker).
JOB_STARTED = EventType.JOB_STARTED
JOB_COMPLETED = EventType.JOB_COMPLETED
JOB_FAILED = EventType.JOB_FAILED

# Per-Turn boundaries (one Cortex round-trip + tool dispatch) — customer-facing.
TURN_STARTED = EventType.TURN_STARTED
TURN_COMPLETED = EventType.TURN_COMPLETED

# Safety + operator-decision milestones.
SAFETY_EVENT = EventType.SAFETY_EVENT
CHECKPOINT_REQUESTED = EventType.CHECKPOINT_REQUESTED  # reserved (operator review milestone)

# Per-rung verification progress (a Job's verify pipeline; one event per rung).
VERIFY_STAGE = EventType.VERIFY_STAGE

# Current Contract B envelope version (breaking rename of kind→type lands here).
SCHEMA_VERSION = "2.0"

__all__ = [
    "CHECKPOINT_REQUESTED",
    "EVENT_TYPES",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_STARTED",
    "MODEL_COMPLETED",
    "MODEL_STARTED",
    "SAFETY_EVENT",
    "SCHEMA_VERSION",
    "SESSION_END",
    "SESSION_STARTED",
    "TURN_COMPLETED",
    "TURN_STARTED",
    "VERIFY_STAGE",
    "EventType",
]
