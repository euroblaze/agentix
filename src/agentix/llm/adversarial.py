"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.adapters.adversarial."""

from agentix.drivers.adapters.adversarial import is_disabled, refute

__all__ = ["is_disabled", "refute"]
