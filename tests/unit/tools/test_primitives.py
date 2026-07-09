"""Pure midlayer primitives — behavioral contracts (#79).

Characterization inputs for ``extract_json_object`` are ported from both
prior call sites (the adversarial verdict parser and an app's pairings
parser) so the merged core provably covers each.
"""

from __future__ import annotations

import datetime as dt
from types import GeneratorType

from agentix.tools import (
    aggregate_by_key,
    batched,
    chunk,
    extract_json_object,
    fingerprint_dict,
)

# ── chunk / batched ─────────────────────────────────────────────────


def test_chunk_splits_with_short_tail() -> None:
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_empty_and_oversize() -> None:
    assert chunk([], 3) == []
    assert chunk([1, 2], 10) == [[1, 2]]


def test_batched_is_lazy_and_equivalent_to_chunk() -> None:
    seq = list(range(7))
    gen = batched(seq, 3)
    assert isinstance(gen, GeneratorType)
    assert list(gen) == chunk(seq, 3)


def test_batched_yields_lists_not_tuples() -> None:
    (first,) = list(batched([1], 5))
    assert type(first) is list


# ── fingerprint_dict ────────────────────────────────────────────────


def test_fingerprint_is_deterministic_and_key_order_insensitive() -> None:
    a = fingerprint_dict({"x": 1, "y": [2, 3]})
    b = fingerprint_dict({"y": [2, 3], "x": 1})
    assert a == b
    assert len(a) == 24


def test_fingerprint_differs_on_content() -> None:
    assert fingerprint_dict({"x": 1}) != fingerprint_dict({"x": 2})


def test_fingerprint_stringifies_dates_via_default() -> None:
    payload = {"since": dt.datetime(2026, 7, 9, 12, 0, 0)}
    assert fingerprint_dict(payload) == fingerprint_dict(dict(payload))


def test_fingerprint_length_param() -> None:
    assert len(fingerprint_dict({"x": 1}, length=64)) == 64


# ── extract_json_object ─────────────────────────────────────────────


def test_extracts_plain_object() -> None:
    assert extract_json_object('{"refuted": true, "reason": "r"}') == {
        "refuted": True,
        "reason": "r",
    }


def test_extracts_from_markdown_fence() -> None:
    content = '```json\n{"pairings": [{"a": 1}]}\n```'
    assert extract_json_object(content) == {"pairings": [{"a": 1}]}


def test_extracts_from_surrounding_prose() -> None:
    content = 'Sure! Here is the result:\n{"k": {"nested": [1, 2]}}\nHope that helps.'
    assert extract_json_object(content) == {"k": {"nested": [1, 2]}}


def test_nested_braces_balance() -> None:
    content = '{"outer": {"inner": {"deep": 1}}} trailing {ignored'
    assert extract_json_object(content) == {"outer": {"inner": {"deep": 1}}}


def test_unbalanced_braces_return_none() -> None:
    assert extract_json_object('{"never": "closed"') is None


def test_no_object_returns_none() -> None:
    assert extract_json_object("no json here") is None
    assert extract_json_object("") is None


def test_non_dict_json_returns_none() -> None:
    # A top-level array is not an object; the first "{" inside it starts
    # the balanced scan, so the inner object is what parses.
    assert extract_json_object('[{"a": 1}]') == {"a": 1}
    assert extract_json_object("[1, 2, 3]") is None


def test_fence_without_newline() -> None:
    assert extract_json_object("```{}") == {}


# ── aggregate_by_key ────────────────────────────────────────────────


def test_aggregate_counts_and_keeps_first_sample() -> None:
    errors = [
        ("fk", "partner_id", "msg-1"),
        ("fk", "partner_id", "msg-2"),
        ("required", None, "msg-3"),
        ("fk", "partner_id", "msg-4"),
    ]
    grouped = aggregate_by_key(errors, key=lambda e: (e[0], e[1]))
    assert grouped[0] == (("fk", "partner_id"), 3, ("fk", "partner_id", "msg-1"))
    assert grouped[1] == (("required", None), 1, ("required", None, "msg-3"))


def test_aggregate_ties_keep_first_seen_order() -> None:
    items = ["b", "a", "b", "a", "c"]
    grouped = aggregate_by_key(items, key=lambda s: s)
    assert [g[0] for g in grouped] == ["b", "a", "c"]


def test_aggregate_empty() -> None:
    assert aggregate_by_key([], key=lambda x: x) == []
