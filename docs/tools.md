# Tools

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

How the kernel's tool subsystem behaves: the contract every tool implements, the
registry, the shipped primitives, the sandbox, the safety gate, and how a call
actually flows. Code: `src/agentix/tools/`. Concepts (tool vs skill vs MCP) and the
four calling verbs live in the proposals — this doc is the landed behavior.

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

## 8. Relation to the four calling verbs

Tool calling is the mechanism; the verbs are what it's used for. *call* is one
dispatch through §6. *consult* arrives as a tool call too — `consult_skill` is
itself a registered tool whose result is know-how text. *compile* removes the model:
the same tools run, driven by a deterministic recipe instead of model choice.
*delegate* is a tool call whose execution leaves the process over A2A. Detail:
`proposals/tool-skill-calling.md` (verbs + lifecycle), `proposals/tools-skills-mcp.md`
(tool vs skill vs MCP grounding).
