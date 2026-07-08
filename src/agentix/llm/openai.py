"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.openai."""

from agentix.drivers.adapters.openai import (
    OpenAIChatDriver,
    _parse_openai_tool_calls,
    _to_openai,
)

OpenAIProvider = OpenAIChatDriver

__all__ = ["OpenAIProvider", "_parse_openai_tool_calls", "_to_openai"]
