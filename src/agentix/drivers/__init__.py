"""agentix.drivers — the kernel's abstraction for external-system I/O.

Public surface grows per phase of the v0.5 re-founding; import from here,
not from submodules. Canonical doc: ``docs/drivers.md``.
"""

from agentix.drivers.base import (
    KNOWN_MODALITIES,
    KNOWN_SOURCES,
    Driver,
    DriverDescriptor,
    DriverError,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.chat import (
    ChatDriver,
    ChatRequest,
    ChatResponse,
    ToolSpec,
    tool_to_spec,
)
from agentix.drivers.cost import CostRecordingChatDriver
from agentix.drivers.embedding import (
    CachedEmbeddingDriver,
    EmbeddingCache,
    EmbeddingDriver,
    EmbeddingError,
    EmbeddingResult,
    HubleEmbeddingDriver,
    OpenAIEmbeddingDriver,
)
from agentix.drivers.limiter import (
    configure_driver_capacity,
    current_limit,
    driver_capacity,
)
from agentix.drivers.router import (
    ChatFailoverChain,
    FailoverCallback,
    NoDriversAvailable,
)
from agentix.drivers.session import (
    bind_session,
    current_session_id,
    session_scope,
    unbind_session,
)

__all__ = [
    "KNOWN_MODALITIES",
    "KNOWN_SOURCES",
    "CachedEmbeddingDriver",
    "ChatDriver",
    "ChatFailoverChain",
    "ChatRequest",
    "ChatResponse",
    "CostRecordingChatDriver",
    "Driver",
    "DriverDescriptor",
    "DriverError",
    "DriverInvalidRequest",
    "DriverRateLimited",
    "DriverUnavailable",
    "EmbeddingCache",
    "EmbeddingDriver",
    "EmbeddingError",
    "EmbeddingResult",
    "FailoverCallback",
    "HubleEmbeddingDriver",
    "NoDriversAvailable",
    "OpenAIEmbeddingDriver",
    "ToolSpec",
    "bind_session",
    "configure_driver_capacity",
    "current_limit",
    "current_session_id",
    "driver_capacity",
    "session_scope",
    "tool_to_spec",
    "unbind_session",
]
