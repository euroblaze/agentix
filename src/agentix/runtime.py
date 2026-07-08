"""Engine-side runtime factories — LLM provider + embedding provider.

Build the provider chain and embedding provider from a ``ResolvedConfig``,
independent of any interface. Extracted from ``cli/main.py`` so the broker
worker (and any engine caller) can construct providers without importing the
CLI package (Locked #3). The CLI re-imports these.
"""

from __future__ import annotations

from agentix.config import KernelConfig
from agentix.storage import SqliteStore


def build_llm_provider(  # type: ignore[no-untyped-def]
    cfg: KernelConfig,
    sqlite: SqliteStore | None = None,
    model_override: str | None = None,
    always_router: bool = False,
):
    """Build the LLM provider chain with auto-failover.

    Multiple configured providers return a ``ProviderRouter`` that
    falls over on LlmUnavailable / LlmRateLimit; a single provider is
    returned directly.

    **model_override**: replaces the HUBLE/Melious provider ``model``
    for this invocation. Anthropic fallback model stays as configured.

    **sqlite**: when provided, each underlying provider is wrapped in
    :class:`CostRecordingProvider`, recording cost to SQLite per
    successful LLM call. Optional for non-migration call sites with no
    session row.

    **always_router**: wrap even a single provider in a failover chain,
    for callers that depend on the chain surface (e.g.
    ``set_failover_callback``) and would otherwise need isinstance
    special-casing.

    MIGRATION SHIM (removed in 0.5.0 final): delegates to
    ``agentix.drivers.factory.build_drivers`` — the *activation* decision
    stays owned by ``agentix.config`` (``enabled_providers`` /
    ``derive_driver_specs``), the composition by the driver factory.
    """
    from agentix.drivers.factory import build_drivers

    registry = build_drivers(
        cfg,
        sqlite=sqlite,
        model_override=model_override,
        always_chain=always_router,
    )
    return registry.chat()


def build_embedding_provider(cfg: KernelConfig, sqlite: SqliteStore) -> object | None:
    """Construct a CachedEmbeddingProvider from configured HUBLE embeddings
    (or OPENAI_API_KEY fallback).

    Returns None when no embedding backend is configured; callers thread
    None into ToolContext.embeddings and downstream code falls back to
    the Jaccard baseline.

    MIGRATION SHIM (removed in 0.5.0 final): delegates to
    ``agentix.drivers.factory.build_drivers``.
    """
    from agentix.drivers.factory import build_drivers

    return build_drivers(cfg, sqlite=sqlite).embedding_or_none()
