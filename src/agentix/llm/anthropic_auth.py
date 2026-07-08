"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.anthropic_auth."""

from agentix.drivers.adapters.anthropic_auth import (
    ChainTokenSource,
    EnvTokenSource,
    FileTokenSource,
    KeychainTokenSource,
    StaticTokenSource,
    TokenSource,
    resolve_token_source,
)

__all__ = [
    "ChainTokenSource",
    "EnvTokenSource",
    "FileTokenSource",
    "KeychainTokenSource",
    "StaticTokenSource",
    "TokenSource",
    "resolve_token_source",
]
