"""MIGRATION SHIM — removed in 0.5.0 final; import from ``agentix.drivers``.

The canonical chat wire types live in ``agentix.drivers.chat``
(``ChatRequest``/``ChatResponse``/``ToolSpec``/``tool_to_spec``); the old
``Llm*`` names below are identity aliases. The ``LlmError`` family lives in
``agentix.drivers._compat`` (dual-inherited into the ``DriverError``
taxonomy). ``Provider`` is the pre-driver chat surface (no ``descriptor``);
new code targets ``agentix.drivers.chat.ChatDriver``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentix.drivers._compat import (
    LlmError,
    LlmInvalidRequest,
    LlmRateLimit,
    LlmUnavailable,
)
from agentix.drivers.chat import (
    ChatRequest,
    ChatResponse,
    ToolSpec,
    tool_to_spec,
)

__all__ = [
    "LlmError",
    "LlmInvalidRequest",
    "LlmRateLimit",
    "LlmRequest",
    "LlmResponse",
    "LlmUnavailable",
    "Provider",
    "ToolSpec",
    "tool_to_spec",
]

# Canonical types, old names. Identity aliases — ``LlmRequest is ChatRequest``.
LlmRequest = ChatRequest
LlmResponse = ChatResponse


@runtime_checkable
class Provider(Protocol):
    """Pre-driver chat protocol (no ``descriptor``). Migration alias surface."""

    name: str
    default_model: str

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Issue a single non-streaming chat completion."""
        ...

    async def aclose(self) -> None:
        """Release underlying HTTP resources."""
        ...
