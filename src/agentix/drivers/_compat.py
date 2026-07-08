"""MIGRATION-WINDOW compat error classes (deleted in 0.5.0 final).

The legacy ``Llm*`` error names, dual-inherited so BOTH vocabularies catch
during the rollout: an adapter raising ``LlmRateLimit`` is caught by
``except LlmError`` (unmigrated consumers) AND by ``except
DriverRateLimited`` / ``except DriverError`` (migrated consumers). The
concrete classes bypass the cooperative ``__init__`` chain and call
``DriverError.__init__`` directly — the two parents' initialisers have
incompatible keyword signatures by design.

At 0.5.0 final this module is deleted and raise sites switch to the
``Driver*`` taxonomy in ``agentix.drivers.base``.
"""

from __future__ import annotations

from agentix.drivers.base import (
    DriverError,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)

__all__ = ["LlmError", "LlmInvalidRequest", "LlmRateLimit", "LlmUnavailable"]


class LlmError(DriverError):
    """Legacy base name for chat-adapter errors. ``provider`` aliases ``driver``."""

    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        DriverError.__init__(self, message, driver=provider, retryable=retryable)

    @property
    def provider(self) -> str:
        return self.driver


class LlmRateLimit(LlmError, DriverRateLimited):
    """Provider signalled a rate limit. Always retryable (chain fallback)."""

    def __init__(self, message: str, *, provider: str) -> None:
        DriverError.__init__(self, message, driver=provider, retryable=True)


class LlmUnavailable(LlmError, DriverUnavailable):
    """Provider is temporarily unreachable (5xx, timeout). Retryable."""

    def __init__(self, message: str, *, provider: str) -> None:
        DriverError.__init__(self, message, driver=provider, retryable=True)


class LlmInvalidRequest(LlmError, DriverInvalidRequest):
    """The request itself is malformed — do not retry the same payload."""

    def __init__(self, message: str, *, provider: str) -> None:
        DriverError.__init__(self, message, driver=provider, retryable=False)
