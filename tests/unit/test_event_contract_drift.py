"""Event-contract drift gate — the kernel's own event vocabulary vs Contract B.

The kernel defines :class:`agentix.event_types.EventType` and the
:class:`agentix.events.SessionEvent` envelope natively (no generated app package
imported — see ``test_kernel_standalone``). The cross-cluster wire contract
``contracts/session-event.schema.json`` remains the canonical seam; this test is
what keeps the two from drifting. If it fails, either the contract changed
(update the kernel enum/envelope — a coordinated Contract B version bump) or the
kernel gained an event the contract doesn't know.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentix.event_types import EVENT_TYPES, EventType
from agentix.events import SessionEvent

_SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "session-event.schema.json"


def _schema() -> dict:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


def test_event_type_enum_matches_contract() -> None:
    schema_types = set(_schema()["properties"]["type"]["enum"])
    kernel_types = {member.value for member in EventType}
    assert kernel_types == schema_types, (
        "agentix.event_types.EventType drifted from contracts/session-event.schema.json:\n"
        f"  kernel-only: {sorted(kernel_types - schema_types)}\n"
        f"  contract-only: {sorted(schema_types - kernel_types)}"
    )
    assert frozenset(EventType) == EVENT_TYPES


def test_session_event_envelope_matches_contract() -> None:
    schema = _schema()
    required = set(schema["required"])
    envelope_fields = set(SessionEvent.model_fields)
    assert envelope_fields == required, (
        "agentix.events.SessionEvent envelope drifted from the contract's required fields:\n"
        f"  kernel-only: {sorted(envelope_fields - required)}\n"
        f"  contract-only: {sorted(required - envelope_fields)}"
    )
    # The contract allows additional payload-adjacent properties; the kernel mirrors that.
    assert schema["additionalProperties"] is True
    assert SessionEvent.model_config.get("extra") == "allow"
