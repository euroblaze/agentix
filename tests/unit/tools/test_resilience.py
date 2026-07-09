"""Failure-recovery midlayer — behavioral contracts (#79).

These pin the micro-contracts app refactors depend on: backoff computed
after the strike increment, strikes persisting across admits, on_halve
firing before recursion, left-before-right merge order, exhaustion attempt
counts, and the on_failure short-circuit semantics.
"""

from __future__ import annotations

import pytest

from agentix.tools import (
    HalvingExhausted,
    TransientRetry,
    bisect_on_failure,
    halve_on_timeout,
)


class _Boom(RuntimeError):
    pass


class _Timeout(RuntimeError):
    pass


# ── TransientRetry ──────────────────────────────────────────────────


def _ledger(max_retries: int = 20, base: float = 20.0) -> TransientRetry:
    return TransientRetry(
        is_transient=lambda exc: isinstance(exc, _Timeout),
        max_retries=max_retries,
        backoff_base_s=base,
    )


def test_delay_sequence_grows_linearly_and_caps() -> None:
    retry = _ledger()
    delays = [retry.admit(_Timeout()) for _ in range(20)]
    assert delays[:3] == [20.0, 40.0, 60.0]
    assert delays[14] == 300.0  # min(20*15, 300)
    assert delays[-1] == 300.0


def test_non_transient_returns_none_without_striking() -> None:
    retry = _ledger()
    assert retry.admit(_Boom()) is None
    assert retry.strikes == 0


def test_exhaustion_after_max_retries() -> None:
    retry = _ledger(max_retries=2)
    assert retry.admit(_Timeout()) == 20.0
    assert retry.admit(_Timeout()) == 40.0
    assert retry.admit(_Timeout()) is None
    assert retry.strikes == 2


def test_strikes_persist_until_reset() -> None:
    retry = _ledger()
    retry.admit(_Timeout())
    retry.admit(_Timeout())
    assert retry.strikes == 2
    retry.reset()
    assert retry.strikes == 0
    assert retry.admit(_Timeout()) == 20.0  # back to base*1


# ── halve_on_timeout ────────────────────────────────────────────────


def _merge_dicts(left: dict, right: dict, _n: int) -> dict:
    return {"ids": left["ids"] + right["ids"]}


@pytest.mark.asyncio
async def test_happy_path_single_attempt_no_hooks() -> None:
    calls: list[list[int]] = []
    halves: list[tuple[int, int, int]] = []

    async def attempt(rows: list[int]) -> dict:
        calls.append(rows)
        return {"ids": rows}

    result = await halve_on_timeout(
        [1, 2, 3],
        attempt,
        is_timeout=lambda e: isinstance(e, _Timeout),
        merge=_merge_dicts,
        on_halve=lambda a, b, c: halves.append((a, b, c)),
    )
    assert result == {"ids": [1, 2, 3]}
    assert calls == [[1, 2, 3]]
    assert halves == []


@pytest.mark.asyncio
async def test_halves_on_timeout_and_merges_left_before_right() -> None:
    halves: list[tuple[int, int, int]] = []
    seen: list[list[int]] = []

    async def attempt(rows: list[int]) -> dict:
        seen.append(rows)
        if len(rows) > 2:
            raise _Timeout()
        return {"ids": rows}

    result = await halve_on_timeout(
        [1, 2, 3, 4],
        attempt,
        is_timeout=lambda e: isinstance(e, _Timeout),
        merge=_merge_dicts,
        on_halve=lambda a, b, c: halves.append((a, b, c)),
    )
    assert result == {"ids": [1, 2, 3, 4]}  # order preserved: left then right
    assert halves == [(4, 2, 1)]  # fired before recursion, attempt_no 1-based
    assert seen[0] == [1, 2, 3, 4]
    assert seen[1] == [1, 2]  # left recursed first


@pytest.mark.asyncio
async def test_on_halve_fires_before_recursion() -> None:
    order: list[str] = []

    async def attempt(rows: list[int]) -> dict:
        order.append(f"attempt:{len(rows)}")
        if len(rows) > 1:
            raise _Timeout()
        return {"ids": rows}

    await halve_on_timeout(
        [1, 2],
        attempt,
        is_timeout=lambda e: isinstance(e, _Timeout),
        merge=_merge_dicts,
        on_halve=lambda a, b, c: order.append(f"halve:{a}->{b}"),
    )
    assert order == ["attempt:2", "halve:2->1", "attempt:1", "attempt:1"]


@pytest.mark.asyncio
async def test_exhaustion_attempts_is_depth_plus_one() -> None:
    async def attempt(rows: list[int]) -> dict:
        raise _Timeout()

    with pytest.raises(HalvingExhausted) as exc_info:
        await halve_on_timeout(
            [1, 2, 3, 4],
            attempt,
            is_timeout=lambda e: isinstance(e, _Timeout),
            merge=_merge_dicts,
        )
    # depth: 4 -> 2 -> 1; singleton timeout at depth 2 => attempts 3
    assert exc_info.value.attempts == 3


@pytest.mark.asyncio
async def test_non_timeout_exception_propagates_unchanged() -> None:
    async def attempt(rows: list[int]) -> dict:
        raise _Boom("not a timeout")

    with pytest.raises(_Boom):
        await halve_on_timeout(
            [1, 2],
            attempt,
            is_timeout=lambda e: isinstance(e, _Timeout),
            merge=_merge_dicts,
        )


# ── bisect_on_failure ───────────────────────────────────────────────


def _outcome(ok: list[int], bad: list[int]) -> dict:
    return {"ok": ok, "bad": bad}


def _merge(left: dict, right: dict) -> dict:
    return {"ok": left["ok"] + right["ok"], "bad": left["bad"] + right["bad"]}


def _make_attempt(failing: set[int], calls: list[list[int]]):
    async def attempt(items: list[int]) -> dict:
        calls.append(items)
        if any(i in failing for i in items):
            return _outcome([], [])  # failure shape: empty result
        return _outcome(list(items), [])

    return attempt


async def _singleton(item: int, _result: dict) -> dict:
    return _outcome([], [item])


@pytest.mark.asyncio
async def test_happy_path_is_single_attempt() -> None:
    calls: list[list[int]] = []
    result = await bisect_on_failure(
        [1, 2, 3, 4],
        _make_attempt(set(), calls),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
    )
    assert result == _outcome([1, 2, 3, 4], [])
    assert calls == [[1, 2, 3, 4]]


@pytest.mark.asyncio
async def test_two_bad_of_eight_isolated() -> None:
    calls: list[list[int]] = []
    result = await bisect_on_failure(
        list(range(1, 9)),
        _make_attempt({3, 6}, calls),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
    )
    assert sorted(result["ok"]) == [1, 2, 4, 5, 7, 8]
    assert sorted(result["bad"]) == [3, 6]


@pytest.mark.asyncio
async def test_on_failure_short_circuits_blind_split() -> None:
    calls: list[list[int]] = []

    async def handled(items: list[int], _r: dict) -> dict:
        return _outcome([i for i in items if i != 3], [3])

    result = await bisect_on_failure(
        [1, 2, 3, 4],
        _make_attempt({3}, calls),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
        on_failure=handled,
    )
    assert result == _outcome([1, 2, 4], [3])
    assert calls == [[1, 2, 3, 4]]  # no blind split happened


@pytest.mark.asyncio
async def test_on_failure_none_falls_through_to_split() -> None:
    calls: list[list[int]] = []
    probed: list[int] = []

    async def not_handled(items: list[int], _r: dict) -> None:
        probed.append(len(items))
        return None

    result = await bisect_on_failure(
        [1, 2, 3, 4],
        _make_attempt({1}, calls),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
        on_failure=not_handled,
    )
    assert sorted(result["ok"]) == [2, 3, 4]
    assert result["bad"] == [1]
    assert probed[0] == 4  # hook saw the full failing batch first


@pytest.mark.asyncio
async def test_on_failure_raise_propagates() -> None:
    async def hard_fail(items: list[int], _r: dict) -> dict:
        raise _Boom("bisection disabled")

    with pytest.raises(_Boom):
        await bisect_on_failure(
            [1, 2],
            _make_attempt({1}, []),
            is_success=lambda r: len(r["ok"]) > 0,
            merge=_merge,
            on_singleton_failure=_singleton,
            on_failure=hard_fail,
        )


@pytest.mark.asyncio
async def test_singleton_failure_hook() -> None:
    result = await bisect_on_failure(
        [7],
        _make_attempt({7}, []),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
    )
    assert result == _outcome([], [7])


@pytest.mark.asyncio
async def test_on_split_reports_sizes() -> None:
    splits: list[tuple[int, int, int]] = []
    await bisect_on_failure(
        [1, 2, 3],
        _make_attempt({2}, []),
        is_success=lambda r: len(r["ok"]) > 0,
        merge=_merge,
        on_singleton_failure=_singleton,
        on_split=lambda n, left, right: splits.append((n, left, right)),
    )
    assert splits[0] == (3, 1, 2)
