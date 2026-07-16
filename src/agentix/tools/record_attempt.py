"""record_attempt — write surface for the session's WorkingMemory.

WorkingMemory (``agentix.core.working_memory``) is the structured
"tried / failed / learned" log that survives per-turn context compression.
``record_attempt`` is the tool that writes into it.

Call it after every meaningful tool attempt — success OR failure — so future
turns in the same session can see what was already tried and why it worked or
didn't.  Failed attempts are automatically added to ``blocked_paths`` so the
agent does not repeat dead ends.  For cross-session persistence use a
separate memory tool (app-supplied) — ``record_attempt`` is session-local only.

This is a kernel builtin: domain-free, no external I/O, no target mutation.
Registered by ``register_kernel_tools`` so it is always available.
"""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from agentix.core.working_memory import AttemptOutcome
from agentix.tools.base import ToolContext, elapsed_ms
from agentix.tools.factory import tool

log = structlog.get_logger(__name__)


class RecordAttemptInput(BaseModel):
    target: str = Field(
        ...,
        description=(
            "What the attempt was directed at — an entity + field, an entity + "
            "action, or a similarly specific identifier. Keep it stable across "
            "repeated attempts on the same thing so repetition can be detected."
        ),
    )
    approach: str = Field(
        ...,
        description=(
            "HOW the attempt was made — the strategy chosen, in one short "
            "phrase. Different attempts on the SAME target should have different "
            "approach strings so the working memory can distinguish 'tried 5 "
            "different strategies' from 'repeated the same one 5 times'."
        ),
    )
    outcome: AttemptOutcome = Field(
        ...,
        description="'success' if the attempt achieved its goal; 'failed' otherwise.",
    )
    lesson: str = Field(
        ...,
        description=(
            "What was learned, stated so a future decision can use it. "
            "On failure: WHY it failed — the rule violated, the constraint hit. "
            "On success: WHAT worked and under what conditions. Be concrete."
        ),
    )
    tool_name: str | None = Field(
        default=None,
        description="The tool the attempt called, if any. Helps detect thrash on a single primitive.",
    )
    add_to_blocked: bool = Field(
        default=False,
        description=(
            "When True, also add this (target, approach) pair to blocked_paths. "
            "Failed attempts are added automatically; set True on a succeeded "
            "attempt only to mark an approach as 'do not retry' for non-failure "
            "reasons (e.g. prohibitively expensive)."
        ),
    )
    set_active_strategy: str | None = Field(
        default=None,
        description=(
            "Optionally replace the session's active_strategy with this string. "
            "Use when this attempt represents a strategic commitment or pivot."
        ),
    )


class RecordAttemptOutput(BaseModel):
    recorded: bool
    target: str
    approach: str
    outcome: AttemptOutcome
    turn_index: int
    blocked_paths_count: int
    attempts_count: int
    active_strategy: str
    notes: list[str] = Field(default_factory=list)
    latency_ms: int = 0


@tool(
    name="record_attempt",
    description=(
        "Record what you just tried and what you learned into this session's "
        "working memory. Working memory survives context compression — call this "
        "after every meaningful tool attempt (success OR failure) so future turns "
        "can see what was already tried and why it worked or didn't. Failed "
        "attempts are automatically added to blocked_paths. For cross-session "
        "persistence, use the app's memory tool instead."
    ),
    mutates_target=False,
)
async def record_attempt(params: RecordAttemptInput, ctx: ToolContext) -> RecordAttemptOutput:
    """Append a structured attempt record to the session's working memory."""
    started = time.perf_counter_ns()

    session = ctx.session
    wm = session.working_memory
    rec = wm.record(
        target=params.target,
        approach=params.approach,
        outcome=params.outcome,
        lesson=params.lesson,
        turn_index=session.turn_index,
        tool_name=params.tool_name,
        add_to_blocked=params.add_to_blocked,
    )
    if params.set_active_strategy is not None:
        wm.set_strategy(params.set_active_strategy)

    log.info(
        "record_attempt.recorded",
        session_id=session.id,
        target=rec.target,
        approach=rec.approach,
        outcome=rec.outcome,
        turn=rec.turn_index,
        tool_name=rec.tool_name,
        blocked_paths_count=len(wm.blocked_paths),
        attempts_count=len(wm.attempts),
    )

    return RecordAttemptOutput(
        recorded=True,
        target=rec.target,
        approach=rec.approach,
        outcome=rec.outcome,
        turn_index=rec.turn_index,
        blocked_paths_count=len(wm.blocked_paths),
        attempts_count=len(wm.attempts),
        active_strategy=wm.active_strategy,
        latency_ms=elapsed_ms(started),
    )


__all__ = [
    "RecordAttemptInput",
    "RecordAttemptOutput",
    "record_attempt",
]
