# Tools

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for tooling in `docs/`.** Sections 1–7 document the landed
kernel tool subsystem (code: `src/agentix/tools/`); sections 8–11 are **DIRECTION** —
converged design, not the code today — consolidated from the retired proposals
`tool-skill-calling.md` and `tools-skills-mcp.md` (their skills content moved to
[`proposals/agent-skills-catalog.md`](proposals/agent-skills-catalog.md)). Tracking:
[euroblaze/ludo #503](https://github.com/euroblaze/ludo/issues/503), sub-issues
#499–502. Not to be confused with dev tooling (ruff, uv, mypy) — that is
[`dev-standards.md`](dev-standards.md), unrelated to agent tools.

---

## 1. The Tool contract

A tool is one callable primitive. Every tool implements the `Tool` protocol
(`tools/base.py`):

- `name` / `description` — what the model sees in the tool catalog.
- `input_schema` / `output_schema` — pydantic models; inputs are validated before the
  tool runs, so a tool body never sees malformed arguments.
- `mutates_target` — declares whether the tool changes the outside world. This one
  flag drives the safety gate (§5).
- `verifier` — the name of the verify-tool to run after a mutation. **A mutating tool
  without a verifier cannot be registered** — the invariant is enforced at
  registration and again at dispatch.
- `required_provider` (optional) — gates registration on an LLM provider being
  configured: `"llm"`/`"*"` = any provider, a concrete name = that one. Most tools
  don't set it.
- `async call(input, ctx) -> BaseModel` — the body.

`ToolContext` is the uniform dependency bundle every call receives: the session, the
three stores (SQLite / object store / memory), `dry_run`, the registry (so tools can
resolve each other, e.g. a declared verifier), and two opaque `source` / `target`
slots for app-supplied remote clients — kept `Any` so the kernel takes no dependency
on any app's client type. Tools ignore what they don't need. `ctx.progress()` emits
best-effort in-flight progress events.

## 2. The registry

`ToolRegistry` (`tools/registry.py`) maps name → tool. Three ways in:

- `register(tool)` — strict: a name conflict or a missing verifier raises. Used for
  kernel and app builtins, where a failure is a bug and should be loud.
- `try_register(tool)` — lenient: log + skip on failure. Used by the skills loader —
  one broken bundle must not take down the service. A skill can never silently
  shadow a builtin (conflicts skip, they don't overwrite).
- `register_provider_gated(tool, available=...)` — skips tools whose
  `required_provider` is unmet, replacing ad-hoc `if provider:` conditionals in apps.

`specs()` converts the catalog to `ToolSpec` JSON-schema advertisements — the
provider-neutral form handed to LLM tool calling.

## 3. Kernel primitives (`tools/builtin.py`)

Two sets, composed onto the app's registry alongside its own tools:

- **Always-on, read-only** — `register_kernel_tools`: `read_file`, `glob_files`,
  `grep_files`, `web_fetch`, plus `write_to_fs` (object-store scratch — writes to
  MinIO, not the filesystem). Safe in any sandbox.
- **Opt-in, mutating** — `register_kernel_module_mode_tools`: `write_file`,
  `apply_patch`, `run_command`, `git_status` / `git_diff` / `git_commit` /
  `git_revert`. Only meaningful once a writable sandbox boundary is active; apps opt
  in for module-port-style work.

## 4. The filesystem sandbox (`tools/_sandbox.py`)

Every primitive that touches the filesystem resolves paths against the active
sandbox — a set of `(path, writable)` boundaries. Outside the boundary raises
`SandboxError`. Two properties:

- **General** — boundaries are plain pairs, so the same tool implementations serve
  module mode (source read-only + output read-write) and workspace mode (one
  read-write root) without per-mode forks. Presets: `set_module_port_sandbox`,
  `set_workspace_sandbox`.
- **Async-safe** — boundaries thread via a `contextvars.ContextVar`, not the Session
  object, so concurrent sessions don't share or leak boundaries.

## 5. The safety gate (`tools/safety.py`)

`SafetyGate.execute` wraps **every** dispatched call with a verify-then-rollback
contract, keyed off `mutates_target`:

1. Non-mutating tools pass straight through.
2. `dry_run` blocks the call, records a `dry_run_block` safety event, raises
   `SafetyGateBlocked`.
3. A mutating tool without a verifier raises `SafetyInvariantViolated`.
4. Otherwise: run the tool → run its declared verifier (an empty `verify_scope` on
   the output means nothing was mutated — verify is skipped) → on drift, record a
   safety event, **roll back**, raise `SafetyVerifyFailed(findings)`.

The kernel ships the flow; two seams are app overrides: `rollback` (required for any
app with mutating tools — the kernel base raises `NotImplementedError`) and
`_resolve_contract` (optional per-model verify contracts; default = count + sample
verification). The verifier's input is built by forwarding same-named fields from
the mutating tool's input, plus app-derived fields via `_derive_verifier_fields`.

## 6. How a call flows (dispatch)

The agent dispatcher (`core/agent_dispatcher.py`) owns the loop:

1. Build the request with the full catalog from `registry.specs()`.
2. The model responds; no `tool_calls` → the turn is done.
3. Per tool call: resolve the name in the registry — an unknown name that looks like
   template bleed gets a closest-match suggestion returned *as the tool result* so
   the model can retry; truly unknown names abort. Coerce arguments through
   `input_schema`, execute via the safety gate, append the result to the
   conversation.
4. Failures are auto-recorded into working memory (`tried/failed`), and recoveries
   that overturn a blocked path are recorded too — the log survives compression.
5. Each result is persisted as a SQLite turn row (with `tool_ok`, `latency_ms`);
   the full session blob checkpoints on a throttled cadence.

## 7. Conventions

- **Token-efficient returns** — return what the model needs to decide the next step,
  not a dump. Bulk payloads go to the object store; the result carries the key.
- **Actionable errors** — an error is a *result the model can act on* (what failed,
  why, what to try), not an exception that kills the run. Validation errors and
  registry misses come back as retryable tool results.
- **Consolidate + namespace** — prefer one tool with a mode argument over near-twins;
  prefix app tools so they can't collide with kernel primitives.
- `elapsed_ms` (`tools/base.py`) is the single home for latency measurement;
  `ensure_input` for input coercion boilerplate.

---

*Everything below is DIRECTION — converged design, not the code today.*

## 8. Tool vs Skill vs MCP — the three concepts

Grounded in Anthropic's published guidance
([writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents),
[Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)):

- **Tool** = a contract between a deterministic system and the non-deterministic
  agent — one callable primitive. *The hammer.* The kernel contract is §1 above; the
  reference app's catalog is `ludo-agent/src/ludo/tools/`.
- **Skill** = a directory (`SKILL.md` + scripts/resources) packaging **procedural
  knowledge** — *when and how to compose tools toward a goal* — with progressive
  disclosure. *The carpentry know-how.* Canonical skills doc:
  [`proposals/agent-skills-catalog.md`](proposals/agent-skills-catalog.md).
- **MCP** = the **transport** that exposes tools (and skills) across process /
  component boundaries. *The shared toolbox other workshops can borrow from.* This
  is what "a Tools-catalog visible to all components" actually is (§11).

## 9. The four calling verbs (#503)

How a capability gets invoked has **four** distinct primitives — not one:

| Verb | What it is | Plane | Cost |
|---|---|---|---|
| **call** a tool | one in-process primitive the LLM invokes (the `Tool` protocol, §1) | vertical, in-process | one tool dispatch |
| **consult** a skill | pull procedural know-how into context on demand (`consult_skill` → `SKILL.md` body) | context, progressive disclosure | an LLM turn |
| **compile** a skill | lift its strategy into deterministic config the body executes | ahead-of-time | **none at runtime** |
| **delegate** | hand the work to another agent over A2A (NATS) | horizontal, cross-process | a job round-trip |

The earlier mental model ("surface skills → LLM consults → composes tools → results
feed back") is only the **consult** verb. Sub-issues: capability levels [#500],
selection [#501], delegate/A2A [#502]; consult↔compile [#499] is §10.

## 10. The consult↔compile lifecycle (#499)

The reference app already has the two end-tiers — they were just never named as one
lifecycle. An escalation falls through a **cost-ordered cascade**:

| Tier | Mechanism (reference app today) | LLM? |
|---|---|---|
| **S3 Compiled** | `build_remediation_router` / `apply_known_fix` matches an `error_catalogue.yaml` recipe and applies it via deterministic tools | none |
| **S1/S2 Consult** | router declines (`None`) → compose recovery → skills surfaced + `consult_skill` body | guided turn |
| **S0 Novel** | no recipe, no skill → reason from scratch + `record_finding` | full reasoning |

The router declines to the agent **only when the recipe needs judgment** — the
compiled tier exists precisely so the model stays asleep for escalations the
deterministic body can absorb.

**The lifecycle = a managed descent S0 → S1 → S3:**

- A novel escalation (S0) → finding → reconciled into memory → authored as a
  **skill** (now S1, consultable). *(This arrow exists: the maturation pipeline.)*
- A skill whose runtime application is **provably invariant** across N
  customers/pairs → **compiled** into a recipe → thereafter handled at **S3**
  deterministically. *(This is the missing arrow.)*

The system's intelligence is the share of traffic the S3 tier absorbs — a concrete
read on the *escalations/customer → 0* metric.

### The gap to close

1. **Single-source the spec and the impl.** Today a strategy lives as three drifting
   artifacts — hand-coded recipe branches, catalogue yaml rows, and skill prose.
   Give a skill a **declarative remediation block** (`{tool, params,
   success_predicate}`, machine-readable) alongside the prose. **Compilation =
   lifting that block into a router recipe**, so one source feeds both consult and
   compile. The prose stays as the human spec + the decline-fallback.
2. **Trace-based compile-readiness.** Each successful consult already emits a
   trajectory + attempt records. Score **invariance** across traces (same tool
   sequence + same param-derivation); past a threshold, flag the skill a **compile
   candidate** for operator review. This reframes skill→core as *emit a
   deterministic executor + demote the skill to evidence/fallback* — not "delete".
3. **Control metric.** Track the S3/S1/S0 share, derivable from existing Contract B
   events.

### Async/NATS leverage — upside without new infrastructure

Consult → compile is the same move as expensive-serial-LLM →
cheap-parallel-idempotent-job — what the NATS substrate already optimizes:

- **The compiled tier is already broker-parallel** — S3 work is deterministic +
  idempotent, so it fans out as independent jobs via queue groups; moving a strategy
  consult→compile also moves it serial→parallel for free.
- **Consult can ride the queue instead of blocking** — routed through a subject, one
  model's LLM recovery never stalls the rest, and recoveries parallelize.
- **Retry/crash-resilience is free** — at-least-once + idempotent execution.
- **Compile-readiness rides the session-close hook**; **the cascade metric is
  event-stream observability** (read the stream, don't add counters); **no registry
  service** — the subject space *is* the registry.

*Honest caveat: not literally zero new code (tag events with a tier; route the
consult subject) — but no new infrastructure or services.*

### Code-saving (CRIE) — the framework shrinks the catalog

- **One declarative recipe collapses 3 paths → 1**: the generic `{tool, params,
  success_predicate}` executed over the existing `Tool` protocol replaces if/elif
  recipe ladders with table-driven dispatch and removes catalogue↔skill drift.
- **Named tool consolidations** (reference app): 5 FK-mapping tools →
  `pin_record(strategy=…)`; 3 memory-lookup tools → `consult_memory(query, kind=…)`.
- **Retire the bespoke skills machinery** (manifest triggers) for the single
  open-standard `SkillCatalog` loader.
- **Reuse, don't add, the registry.**

The unifying point: the declarative, Tool-protocol-executed recipe is
*simultaneously* what rides the NATS rails **and** what collapses the redundant
code paths — one lever seen from two sides.

### First increments (under #499)

1. **Consult tier wiring** — surface `SkillCatalog.describe()` into the agent's
   context at session start + an always-on `consult_skill(name)` builtin (reads the
   body from the real skills root; `read_file` is sandboxed and can't).
2. **The compiler link** — declarative remediation block on skills → router recipe;
   trace-invariance scoring → compile-candidate flag at session close.

## 11. The cluster tools-catalog (MCP) — kernel-phase

**Only one component is agentic.** In the reference cluster, tools and skills are a
`ludo-agent` concern; every other component (gateway, webapps, CLI, desktop) is a
deterministic *client* that triggers the agent or *transport* that carries
invocations + events. The cluster value is (a) getting the agent's tools/skills
right and (b) **publishing them as a discoverable catalog** so any future agentic
surface reuses them instead of re-implementing.

"A Tools-catalog visible to all components" = an **MCP surface**, namespaced
(`ludo_extract`, `ludo_verify`, …), **published through the gateway** (the single
public door). Seed already exists: `omg tools list` + the app's builtin
registration. Consumers, only if/when they go agentic: a desktop local assistant,
CLI-as-MCP-tools (like `gh`), a future support/sales agent. **Post-autonomy, not
now.**

Reference-app catalog assessment (against the guidance's levers — consolidation,
namespacing, token-efficient returns, actionable errors): the ~37 migration
primitives are capability-complete; the work is consolidation, not new tool
families. Detail lives with the app (`ludo-agent`).
