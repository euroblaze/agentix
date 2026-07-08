"""MIGRATION SHIM — removed in 0.5.0 final; import from agentix.drivers.limiter."""

from agentix.drivers.limiter import (
    configure_driver_capacity,
    current_limit,
    driver_capacity,
)

llm_capacity = driver_capacity
configure_llm_capacity = configure_driver_capacity

__all__ = ["configure_llm_capacity", "current_limit", "llm_capacity"]
