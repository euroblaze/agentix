"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.cost / .session."""

from agentix.drivers.cost import CostRecordingChatDriver, _extract_real_cost
from agentix.drivers.session import (
    bind_session,
    current_session_id,
    session_scope,
    unbind_session,
)

CostRecordingProvider = CostRecordingChatDriver

__all__ = [
    "CostRecordingProvider",
    "_extract_real_cost",
    "bind_session",
    "current_session_id",
    "session_scope",
    "unbind_session",
]
