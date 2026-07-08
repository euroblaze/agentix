# Agentix — the agentic-app kernel

**Agentix** is a reusable, app-agnostic kernel for building agentic applications: a
**deterministic body** that runs the routine work, and wakes an LLM (the *Cortex*) only on
**cognitive escalation** — when an automated step cannot prove its result is correct. Apps
supply domain tools, prompts and memory sources; the kernel supplies everything else — the
engine and middleware spine, the LLM provider router, sessions and checkpoints, context
management, tools and skills, three-store persistence, budgets, isolation and safety.

A strict `[K]` kernel / `[A]` app split keeps domain vocabulary out of the core, enforced by
CI purity gates. The kernel is the frozen API + principles; any terminal, web, mobile or
desktop agent app builds on it by registering its own tools, skills, job types and policies.

## Install

Python **3.12** + [uv](https://docs.astral.sh/uv/):

```sh
uv sync                    # kernel + dev tooling
uv sync --extra broker     # + nats-py, only when running against a message broker
```

## Quickstart

The kernel takes a *resolved* `KernelConfig` — apps own YAML/env loading and subclass it to
attach their own settings (env fallbacks: [`docs/kernel-config-reference.md`](docs/kernel-config-reference.md)).

```python
from pathlib import Path

from agentix.config import KernelConfig
from agentix.core.agent_dispatcher import AgentDispatcher
from agentix.core.engine import Engine
from agentix.core.session import create_session
from agentix.core.types import Message
from agentix.runtime import build_llm_provider
from agentix.storage import MemoryStore, MinioConfig, MinioStore, SqliteStore
from agentix.tools.base import ToolContext
from agentix.tools.builtin import register_kernel_tools
from agentix.tools.registry import ToolRegistry
from agentix.tools.safety import SafetyGate

cfg = KernelConfig(
    config_path=Path("app.yaml"),
    minio=MinioConfig(endpoint="10.0.99.1:9000", access_key="...", secret_key="..."),
    sqlite_path=Path("data/kernel.db"),
    memory_path=Path("data/memory"),
)

# Three stores: operational state (SQLite), checkpoint blobs (object store), memory pages.
sqlite = SqliteStore(cfg.sqlite_path)
await sqlite.initialize()
minio = MinioStore(cfg.minio)
await minio.ensure_bucket()
memory = MemoryStore(cfg.memory_path)

registry = ToolRegistry()
register_kernel_tools(registry)      # always-on read-only primitives
# registry.register(MyDomainTool())  # app tools plug in here

session = await create_session(sqlite, customer_id="tenant-1", budget_usd=50.0)

dispatcher = AgentDispatcher(
    provider=build_llm_provider(cfg, sqlite=sqlite),   # provider chain with auto-failover
    registry=registry,
    safety_gate=SafetyGate(sqlite=sqlite),             # verify-then-rollback on mutations
    ctx_factory=lambda turn: ToolContext(session=session, sqlite=sqlite, minio=minio, memory=memory),
)
engine = Engine(sqlite=sqlite, minio=minio, middlewares=[], dispatcher=dispatcher)

turn = await engine.run_turn(session, Message(role="user", content="Summarise data/report.csv"))
```

`middlewares=[]` is the minimal chain; real apps compose the kernel layers (trajectory
capture, cost tracking, token budget, safety gate, loop detection, retry — see
`src/agentix/core/middleware/`) and may extend the order with their own.

## Core concepts

### Kernel / app split

`src/agentix` carries no app-domain vocabulary in its code surface. Two CI gates enforce it:
`tests/unit/test_kernel_purity.py` (AST scan — no forbidden terms in identifiers or string
literals) and `tests/unit/test_kernel_standalone.py` (importing the kernel pulls in no app
module). Apps plug in via seams only (see [How an app plugs in](#how-an-app-plugs-in)).

### Engine and dispatch

A turn engine (`core/engine.py`) runs an ordered middleware chain around each step; the
agent dispatcher (`core/agent_dispatcher.py`) owns the LLM loop — build request, call the
provider, dispatch tool calls, append results — bounded by `max_tool_iterations`. Messages
are an opaque list the engine snapshots per turn. The innermost dispatch is a
`TurnDispatcher` protocol, so tests swap in fakes without touching the chain.

### Cognitive escalation

An *escalation* happens when an automated step cannot prove its result is correct. The
deterministic body handles the routine; an escalation is the only event that wakes the
model. Escalations descend the **escalation ladder** — compiled recipe (model stays asleep)
→ consult skill → novel reasoning — so the cheapest competent path wins; the loop then
re-runs the step to re-prove it. If the budget is spent before the step proves clean, the
agent performs an *operator handoff* (escalation = body wakes the model; handoff = agent
gives up to a human). The share of escalations absorbed at the compiled tier is the
system's intelligence; the product metric is *escalations/customer → 0*.
Detail: [`docs/tools.md`](docs/tools.md).

### Four calling verbs

The caller is always the model, woken by an escalation. The four verbs are the four ways it
can get work done:

- ***call* a tool** — do one thing now, in-process.
- ***consult* a skill** — pull the full know-how text into context, then act on its steps.
- ***compile* a skill** — turn know-how into a deterministic recipe; next time the body
  applies it and the model stays asleep.
- ***delegate*** — hand the task to another agent over A2A.

Detail and worked examples: [`docs/tools.md`](docs/tools.md), [`docs/skills.md`](docs/skills.md).

### Tools

A tool is one callable primitive implementing the `Tool` protocol (`tools/base.py`):
pydantic input/output schemas, a `mutates_target` flag, and a declared `verifier` — **a
mutating tool without a verifier cannot be registered**. `ToolRegistry` maps name → tool
with provider-neutral spec conversion; the kernel ships always-on read-only primitives
(read, glob, grep, fetch) plus opt-in mutating sandbox primitives (write, patch, shell,
git). The `SafetyGate` executes mutations verify-then-rollback, with rate-limit,
quiet-hours, idempotency and audit around them.
Detail: [`docs/tools.md`](docs/tools.md) (contract, registry, sandbox, safety gate, dispatch flow).

### Skills

The [Agent Skills](https://agentskills.io) open standard, loaded by an agent-agnostic
catalog with **progressive disclosure** — cheap name and description at session start, full
body on demand — so the window stays lean.
Detail: [`docs/skills.md`](docs/skills.md) (bundle layout, catalog, consult_skill, loader).

### Sessions

The checkpoint-first, resumable unit of a run: create, save, resume-from. Operational state
in SQLite, full state blob in the object store. App scope is opaque `app_meta`; sessions
carry a control-plane binding and a parent link for streaming and delegation hierarchy.
Detail: [`docs/session.md`](docs/session.md) (object, persistence, checkpoints, resume, operator pause, lease).

### Context management

One owner of the model window — assemble, budget, compress, evict by priority tier
(guardrails > goal > working set > retrieved memory > history), with a per-turn *window
report* of what entered and why.
Detail: [`docs/context.md`](docs/context.md) (budget, tiers, compression, window report).

### Working memory and memory tiers

Working memory is a structured tried / failed / learned log that survives context
compression, auto-recorded on tool failure and on recoveries that overturn a blocked path,
and rendered into a system message every turn. It is the transient tier of three memory
classifications — **Transient** (one run), **Episodic** (per-tenant and per-context),
**Learnings** (general) — with verbs to reconcile a finding into a rule and promote it on
cross-case evidence.
Detail: [`docs/memory.md`](docs/memory.md) (working memory, page store, semantic recall, maintain seam).

### Budgets (token economics)

Per-session and per-account spending ceilings, in money; cost is recorded at each LLM call,
not after the fact.

- **Safety** — no human approves anything mid-run, so the budget is what ends a hopeless
  retry loop: when it runs out, the agent stops and hands off honestly instead of trying forever.
- **Economics** — tokens cost money; the account ceiling stops one expensive tenant from
  eating the margin of the others.
- **Design pressure** — every escalation has a price, so the system is pushed to solve
  problems the cheap way and to learn; it gets smarter by learning, not by spending more.

A budget caps how often the model is woken, never how hard it thinks in a turn. Ceilings
are policy: set per account, or lifted entirely. The model-window budget is a separate
thing — see [Context management](#context-management).

### Storage

Three stores, one invariant: **data and memory never cross.**

- an async **SQLite** store (WAL, busy-timeout, FTS5 search, schema-versioned migrations)
  for operational state — schema: [`docs/sqlite_schema.sql`](docs/sqlite_schema.sql);
- an **object store** for checkpoints and bulk data;
- a **markdown memory** store for episodic pages and learnings.

Detail: [`src/agentix/storage/README.md`](src/agentix/storage/README.md).

### Isolation and concurrency

One session = one context = one task-tree root; only distilled context crosses any
boundary. Per-task cost and DB scoping, structured concurrency, a session lease with an
orphan reaper, and trust-zone broker accounts (edge / control / internal), deny-by-default.
Detail: [`docs/isolation.md`](docs/isolation.md) (axiom, planes, invariants I1–I7, session hierarchy).

### A2A

Agent-to-agent over the broker: capability subjects as the registry, an agent card as the
INFO reply, the *delegate* verb, and activatable key-gated agents with a deterministic
fallback when no key is present. The kernel ships the discovery model (`a2a/card.py`).
Detail: [`docs/a2a.md`](docs/a2a.md) (agent card, delegate crossing, deferred substrate).

### Evaluation

A Verdict spine grading both responses and outcomes, with an activatable LLM judge; honest
outcome labels derived from verification rather than the agent's (or the Cortex's) own claim.

### Contracts and codegen

Versioned wire contracts as the single source of truth, generating Python, TypeScript and
Swift, with cross-repo drift guards so consumers never hand-maintain parallel copies.
Detail: [`docs/contracts-consumer-guide.md`](docs/contracts-consumer-guide.md) and [`contracts/`](contracts/).

## Package tour

| Path | What lives there |
|---|---|
| `src/agentix/core/` | Engine spine: `Engine`, `AgentDispatcher`, `Session` + `create_session`, checkpoints, `ContextManager`, `WorkingMemory`, `Message`/`Turn` types, `middleware/` (trajectory, cost, budget, safety gate, loop detection, retry, dangling-tool-call, tool-count cap) |
| `src/agentix/llm/` | `Provider` protocol + adapters (Anthropic incl. OAuth, OpenAI-compatible, Groq, gateway), `ProviderRouter` auto-failover, cost recorder, rate limiter, adversarial judge |
| `src/agentix/tools/` | `Tool` protocol, `ToolContext`, `ToolRegistry`, `SafetyGate`, kernel primitives (`builtin.py`, `spike/`), sandbox |
| `src/agentix/skills/` | `SkillCatalog`, `consult_skill`, bundle loader |
| `src/agentix/storage/` | `SqliteStore`, `MinioStore`, `MemoryStore` |
| `src/agentix/a2a/` | `AgentCard`, `Capability` — the discovery model |
| `src/agentix/config.py` | `KernelConfig` + per-provider configs; apps subclass |
| `src/agentix/runtime.py` | `build_llm_provider` / `build_embedding_provider` factories |
| `src/agentix/events.py` | Session event bus + wire-contract event types |
| `src/agentix/embeddings.py` | `EmbeddingProvider` protocol + deterministic fallback |

## How an app plugs in

The kernel is extended only through these seams — never by editing kernel code:

- **`KernelConfig` subclass** — attach the app's resolved settings.
- **`SafetyGate` hooks** — override `rollback` (required with mutating tools),
  `_resolve_contract`, `_derive_verifier_fields`.
- **Dispatcher policies** — `TerminationPolicy` and `DispatchGuard` on `AgentDispatcher`.
- **`Tool` implementations** and exception `to_error_details()` for actionable errors.
- **Allowlist extenders** — `register_allowed_hosts` (web fetch), `register_allowed_binaries` (shell).
- **Middleware** — compose the kernel chain (a prefix is fine) and extend it with app layers.
- **Skills** — drop bundles under the app's `skills_root`; the catalog discovers them.

## Kernel docs

| Doc | Single source of truth for |
|---|---|
| [`docs/tools.md`](docs/tools.md) | Tool contract, registry, kernel primitives, safety gate, the escalation ladder, the four verbs |
| [`docs/skills.md`](docs/skills.md) | Skill bundles, catalog, progressive disclosure, loader |
| [`docs/session.md`](docs/session.md) | Session object, persistence, checkpoints, resume, lease |
| [`docs/context.md`](docs/context.md) | Window assembly, budget, compression, eviction tiers, window report |
| [`docs/memory.md`](docs/memory.md) | Working memory, memory tiers, page store, semantic recall |
| [`docs/isolation.md`](docs/isolation.md) | Runtime isolation model, invariants I1–I7, trust zones |
| [`docs/a2a.md`](docs/a2a.md) | Agent-to-agent: card, delegate crossing, deferred substrate |
| [`docs/kernel-config-reference.md`](docs/kernel-config-reference.md) | Env vars the kernel reads, provider activation, pricing |
| [`docs/sqlite_schema.sql`](docs/sqlite_schema.sql) | Operational-store DDL |
| [`docs/contracts-consumer-guide.md`](docs/contracts-consumer-guide.md) | Thin-client consumption of the public REST + SSE contract |

## Repo layout (shared machinery)

Beyond the kernel package, this repo owns the cross-repo machinery consumers vendor:

| Path | What |
|---|---|
| `contracts/` | Canonical versioned wire contracts (OpenAPI + JSON Schema) + shared types |
| `constants/cluster.yaml` | Single source for shared values (network, ports, env stages, locale) |
| `templates/` | `gitignore.base` · `ruff.toml` · `env.template` — vendored/aligned into consumer repos |
| `libs/` | Canonical shared wire-contract packages, generated from `contracts/` + `constants/` by `scripts/gen_shared.py`; shipped with the wheel |
| `scripts/` | Codegen (`gen_shared.py`, `gen_ts.py`, `gen_swift.py`) + drift guards (`check_contract_drift.py`, `check_config_drift.py`) |
| `tests/` | Kernel unit + integration suites, including the two purity gates |

## Development

- `uv sync`, then `ruff` format/lint + `mypy` clean before any PR.
- Kernel unit surface: `PYTHONPATH=src pytest tests/unit` (the full suite is heavy — run on demand).
- Integration tests need live SQLite/MinIO or a provider key (`-m integration`).

## License

BSL 1.1 — see [`LICENSE`](LICENSE).
