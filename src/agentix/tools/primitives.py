"""Pure midlayer primitives — stdlib-only, synchronous, side-effect-free.

The pure half of the driver midlayer (#79): small building blocks any app
tool would otherwise reimplement. This module imports nothing outside the
standard library by design — ``drivers/`` code may import it without any
risk of a cycle. The async failure-recovery loops live in
:mod:`agentix.tools.resilience`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

__all__ = [
    "aggregate_by_key",
    "batched",
    "chunk",
    "extract_json_object",
    "fingerprint_dict",
]


def chunk[T](seq: list[T], n: int) -> list[list[T]]:
    """Consecutive sublists of length ``n`` (the last may be shorter). Eager."""
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def batched[T](seq: list[T], n: int) -> Iterator[list[T]]:
    """Lazy variant of :func:`chunk` — yields lists.

    Deliberately NOT ``itertools.batched``, which yields tuples; callers
    index and mutate the slices as lists.
    """
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def fingerprint_dict(payload: Mapping[str, Any], *, length: int = 24) -> str:
    """Stable content key for a payload dict — same inputs, same key.

    The serialization parameters ARE the contract: ``sort_keys=True`` makes
    the key order-insensitive, ``default=str`` admits dates and other
    stringifiable values. Content-addressed caches depend on this byte
    stability across sessions — do not change them.
    """
    canonical = json.dumps(dict(payload), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def extract_json_object(content: str) -> dict[str, Any] | None:
    """Tolerant JSON-from-LLM extraction: strip fences, first balanced ``{...}``.

    Tolerates surrounding prose and markdown code fences; returns the first
    top-level JSON object, or ``None`` when nothing parseable is found.
    Callers validate the keys they need (a verdict's ``refuted``, a
    proposal list, ...) — this owns only the extraction.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    try:
        obj = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def aggregate_by_key[T, K](items: Iterable[T], key: Callable[[T], K]) -> list[tuple[K, int, T]]:
    """Group ``items`` by ``key(item)`` into ``(key, count, first_item)`` triples.

    Sorted by count descending; ties keep first-seen order (dict insertion
    order under a stable sort — that tie order is part of the contract).
    The first item seen per group is kept as the representative sample.
    """
    groups: dict[K, tuple[int, T]] = {}
    for item in items:
        k = key(item)
        if k in groups:
            count, first = groups[k]
            groups[k] = (count + 1, first)
        else:
            groups[k] = (1, item)
    return sorted(
        ((k, count, first) for k, (count, first) in groups.items()),
        key=lambda g: -g[1],
    )
