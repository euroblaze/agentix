"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.huble."""

from agentix.drivers.adapters.huble import (
    HubleChatDriver,
    _looks_like_wrapped_4xx,
    _message_to_huble,
    _parse_huble_response,
    _split_system,
    _status_message,
)

HubleProvider = HubleChatDriver

__all__ = [
    "HubleProvider",
    "_looks_like_wrapped_4xx",
    "_message_to_huble",
    "_parse_huble_response",
    "_split_system",
    "_status_message",
]
