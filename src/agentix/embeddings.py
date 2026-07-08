"""MIGRATION SHIM — removed in 0.5.0 final; import from ``agentix.drivers.embedding``
(driver family) and ``agentix.storage.vector_index`` (CosineIndex)."""

from agentix.drivers.embedding import (
    CachedEmbeddingDriver,
    EmbeddingCache,
    EmbeddingDriver,
    EmbeddingError,
    EmbeddingResult,
    HubleEmbeddingDriver,
    OpenAIEmbeddingDriver,
)
from agentix.storage.vector_index import CosineIndex

EmbeddingProvider = EmbeddingDriver
OpenAIEmbeddingProvider = OpenAIEmbeddingDriver
HubleEmbeddingProvider = HubleEmbeddingDriver
CachedEmbeddingProvider = CachedEmbeddingDriver

__all__ = [
    "CachedEmbeddingProvider",
    "CosineIndex",
    "EmbeddingCache",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingResult",
    "HubleEmbeddingProvider",
    "OpenAIEmbeddingProvider",
]
