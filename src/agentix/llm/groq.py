"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.groq."""

from agentix.drivers.adapters.groq import GroqChatDriver

GroqProvider = GroqChatDriver

__all__ = ["GroqProvider"]
