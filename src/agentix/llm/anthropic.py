"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.anthropic."""

from agentix.drivers.adapters.anthropic import (
    _DEFAULT_BILLING_HEADER,
    AnthropicChatDriver,
    _billing_header,
    _from_anthropic_response,
    _infer_default_model,
    _message_to_anthropic,
    _split_system,
)

AnthropicProvider = AnthropicChatDriver

__all__ = [
    "_DEFAULT_BILLING_HEADER",
    "AnthropicProvider",
    "_billing_header",
    "_from_anthropic_response",
    "_infer_default_model",
    "_message_to_anthropic",
    "_split_system",
]
