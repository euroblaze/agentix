"""Pure-Python cosine-similarity index.

Not a driver concept — in-memory math over vectors the embedding driver
family produced. Lives in storage beside the stores that persist those
vectors. For 10k+ entries swap the implementation to FAISS or hnswlib;
the interface is stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

__all__ = ["CosineIndex"]


@dataclass
class _IndexEntry:
    key: str
    payload: dict[str, Any]
    vector: tuple[float, ...]
    norm: float


@dataclass
class CosineIndex:
    """Add entries with :meth:`add`, query with :meth:`top_k`. The vectors
    are kept verbatim (no PCA / quantisation) — small catalogues only.
    """

    entries: list[_IndexEntry] = field(default_factory=list)

    def add(self, *, key: str, payload: dict[str, Any], vector: tuple[float, ...]) -> None:
        norm = _l2_norm(vector)
        if norm == 0.0:
            log.warning("embeddings.zero_vector", key=key)
            return
        self.entries.append(_IndexEntry(key=key, payload=payload, vector=vector, norm=norm))

    def top_k(self, query_vec: tuple[float, ...], k: int = 3) -> list[tuple[float, _IndexEntry]]:
        """Return the top-``k`` entries by cosine similarity, descending."""
        if not self.entries:
            return []
        q_norm = _l2_norm(query_vec)
        if q_norm == 0.0:
            return []
        scored: list[tuple[float, _IndexEntry]] = []
        for entry in self.entries:
            score = _dot(query_vec, entry.vector) / (q_norm * entry.norm)
            scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self.entries)


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _l2_norm(v: tuple[float, ...]) -> float:
    return math.sqrt(sum(x * x for x in v))
