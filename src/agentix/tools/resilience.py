"""Failure-recovery midlayer — retry ledger, timeout halving, failure bisection.

The async half of the driver midlayer (#79): the recovery *mechanisms* any
bulk remote-call tool needs, with every *policy* decision (what counts as
transient, what a result means, what to log) supplied by the caller as a
callback. The kernel never calls up into named app modules and emits no
log events of its own — observability belongs to the caller.

Distinct from :class:`agentix.core.middleware.retry.RetryMiddleware`,
which transparently retries kernel PROVIDER (LLM) calls flagged
``retryable`` by the driver error taxonomy. The helpers here are for
tool-owned remote-call loops the middleware never sees.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

__all__ = [
    "HalvingExhausted",
    "TransientRetry",
    "bisect_on_failure",
    "halve_on_timeout",
]


class TransientRetry:
    """Strike ledger for transient-failure retry across an app-driven loop.

    The caller owns the loop, the sleep, the logging and the
    ``is_transient`` policy; the ledger owns strike counting and backoff
    math. Strikes deliberately persist across calls — including successful
    but unproductive ones — and clear only when the caller reports domain
    progress via :meth:`reset`. (A per-call retry wrapper would reset on
    every invocation, which is exactly the behavior this class exists to
    avoid.)
    """

    def __init__(
        self,
        *,
        is_transient: Callable[[BaseException], bool],
        max_retries: int,
        backoff_base_s: float,
        backoff_cap_s: float = 300.0,
    ) -> None:
        self._is_transient = is_transient
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._backoff_cap_s = backoff_cap_s
        self.strikes = 0

    def admit(self, exc: BaseException) -> float | None:
        """Record ``exc`` and return the backoff sleep in seconds.

        ``None`` means the caller must abort: the exception is not
        transient, or the retry budget is exhausted. Otherwise a strike is
        recorded and the delay is ``min(base * strikes, cap)`` — computed
        after the increment, so the first retry sleeps ``base * 1``.
        """
        if not self._is_transient(exc):
            return None
        if self.strikes >= self._max_retries:
            return None
        self.strikes += 1
        return min(self._backoff_base_s * self.strikes, self._backoff_cap_s)

    def reset(self) -> None:
        """Clear the strike count — call on domain progress."""
        self.strikes = 0


class HalvingExhausted(RuntimeError):
    """Still timing out at batch size 1 after ``attempts`` halvings."""

    def __init__(self, attempts: int) -> None:
        super().__init__(f"call timed out at batch_size=1 after {attempts} retries")
        self.attempts = attempts


async def halve_on_timeout[T, R](
    items: list[T],
    attempt: Callable[[list[T]], Awaitable[R]],
    *,
    is_timeout: Callable[[BaseException], bool],
    merge: Callable[[R, R, int], R],
    on_halve: Callable[[int, int, int], None] | None = None,
) -> R:
    """Run ``attempt(items)``; on timeout, halve recursively and merge.

    A slice that still times out at size 1 raises :class:`HalvingExhausted`
    with the attempt count (depth + 1). Exceptions ``is_timeout`` rejects
    propagate unchanged. ``on_halve(from_size, to_size, attempt_no)`` fires
    BEFORE recursing — callers that append warnings rely on that ordering.
    ``merge(left, right, item_count)`` receives the item count of the level
    being merged.
    """

    async def _recurse(rows: list[T], attempt_no: int) -> R:
        try:
            return await attempt(rows)
        except BaseException as exc:
            if not is_timeout(exc):
                raise
            if len(rows) <= 1:
                raise HalvingExhausted(attempt_no + 1) from exc
            mid = len(rows) // 2
            if on_halve is not None:
                on_halve(len(rows), mid, attempt_no + 1)
            left = await _recurse(rows[:mid], attempt_no + 1)
            right = await _recurse(rows[mid:], attempt_no + 1)
            return merge(left, right, len(rows))

    return await _recurse(items, 0)


async def bisect_on_failure[T, R](
    items: list[T],
    attempt: Callable[[list[T]], Awaitable[R]],
    *,
    is_success: Callable[[R], bool],
    merge: Callable[[R, R], R],
    on_singleton_failure: Callable[[T, R], Awaitable[R]],
    on_failure: Callable[[list[T], R], Awaitable[R | None]] | None = None,
    on_split: Callable[[int, int, int], None] | None = None,
) -> R:
    """Binary-search a failing batch down to the items that actually fail.

    The recursion skeleton only — the caller interprets results:

    1. ``result = await attempt(items)``; ``is_success(result)`` → return it.
    2. Single item → ``await on_singleton_failure(item, result)`` (the
       caller quarantines/records and returns its outcome shape).
    3. ``on_failure(items, result)`` escape hatch: a returned ``R``
       short-circuits the blind split (e.g. the caller extracted per-item
       failure indices from the result and handled them itself, possibly
       re-entering this function on the survivors); ``None`` falls through;
       a raise propagates (e.g. bisection disabled → hard fail).
    4. Blind split: ``on_split(size, left, right)``, recurse both halves,
       ``merge(left, right)``.
    """
    result = await attempt(items)
    if is_success(result):
        return result
    if len(items) == 1:
        return await on_singleton_failure(items[0], result)
    if on_failure is not None:
        handled = await on_failure(items, result)
        if handled is not None:
            return handled
    mid = len(items) // 2
    if on_split is not None:
        on_split(len(items), mid, len(items) - mid)
    left = await bisect_on_failure(
        items[:mid],
        attempt,
        is_success=is_success,
        merge=merge,
        on_singleton_failure=on_singleton_failure,
        on_failure=on_failure,
        on_split=on_split,
    )
    right = await bisect_on_failure(
        items[mid:],
        attempt,
        is_success=is_success,
        merge=merge,
        on_singleton_failure=on_singleton_failure,
        on_failure=on_failure,
        on_split=on_split,
    )
    return merge(left, right)
