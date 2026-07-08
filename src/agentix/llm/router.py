"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.router."""

from agentix.drivers.router import (
    ChatFailoverChain,
    FailoverCallback,
    NoDriversAvailable,
)

ProviderRouter = ChatFailoverChain
NoProvidersAvailable = NoDriversAvailable

__all__ = ["FailoverCallback", "NoProvidersAvailable", "ProviderRouter"]
