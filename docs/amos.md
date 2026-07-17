# AMOS — Agentic MicroServers for SysOps

*Integrated Architecture Design — Single-binary agent runtime on gVisor, trusted broker outside agent, three-layer orchestration*

**Version 2.0 — Integrated Design (English Edition)**

- Release date: July 12, 2026
- Topics: Agent runtime · gVisor sandbox · Capability broker · Plan-execute dataflow · Temporal orchestration · Harness Engineering
- Reference stack: Python · ReactJS · Ansible · OpenStack · Docker · Kubernetes · Go (agentd)

## Table of Contents

# 1. Summary

AMOS (Agentic MicroServers) is a SysOps platform powered by LLM agents, designed to execute tasks on customer VMs without requiring KVM/nested virtualization, without inbound SSH, while achieving significantly stronger isolation than standard containers.
This v2.0 document consolidates all architecture decisions: gVisor (runsc systrap) instead of hardware microVMs since no KVM is available; the entire logic running on the target VM is packaged as a single static binary (agentd) with three clearly separated trusted roles; three-layer orchestration MACRO/MESO/MICRO where Temporal holds the static macro order, AI decides dynamic order and dataflow at the meso layer, and the broker enforces the allow-list at the micro layer; and dataflow between tools uses references rather than raw values typed by the LLM.

# 2. Background & Foundational Principles

## 2.1. Agent = Model + Harness

A production AI agent is not just a model. The model provides reasoning capability - increasingly a commodity. Reliability comes from the harness: the entire environment surrounding the model including rules it must follow, checks it must pass, and feedback loops that prevent mistakes from recurring. The harness is a compounding asset because it encodes business rules, data context, and the organization's own safety constraints.
The shift in focus: prompt engineering (optimizing a single query) -> context engineering (designing what the model sees at inference time) -> harness engineering (designing the entire environment when an agent acts autonomously across many steps).

## 2.2. Harness Engineering (Hashimoto, Feb 2026)

The term was coined by Mitchell Hashimoto - co-founder of HashiCorp, creator of Terraform and Ghostty - on February 5, 2026. The definition is simple: whenever an agent makes a mistake, invest the engineering effort to create a solution so the agent never makes that exact mistake again. Fix the structure, not the symptom. Reliability compounds over time.
Applied to AMOS: the Harness Registry is the versioned source of truth for guides + sensors + capability manifests, applied fleet-wide. **Every production mistake -> root-cause analysis -> add guide / sensor / tighten arg constraint / tighten allow-list -> update registry**. Old mistakes become structurally impossible.

## 2.3. Two Foundational Principles of AMOS

**Principle 1  —  Untrusted brain, trusted broker. **The LLM brain is always treated as already compromised. It has no shell on the host. It can only emit *requests* via a narrow channel to a trusted broker sitting outside the sandbox. The broker holds the allow-list, budget, idempotency, and is the entity that actually executes. Compromising the brain ⇒ cannot exec anything outside the manifest. This mirrors the *capability mediation* and *object capability* principles in traditional secure systems design.
**Principle 2  —  Managed runtime in the style of BEAM. **The agent runtime owns and supervises agent lifecycle like BEAM (Erlang) owns its processes: isolated actors + message passing + supervisor tree + preemptive budget + per-actor heap. Key lesson from JVM SecurityManager: **never make the runtime itself the sandbox within the same trust domain**. The runtime provides the programming model & lifecycle; real enforcement must be delegated to the OS/sandbox layer (gVisor).

# 3. Three-Layer Architecture: MACRO · MESO · MICRO

AMOS divides responsibility into three layers with very different properties - and also three different types of 'ordering' in the system. Keeping them clearly separated allows choosing the right tool for each layer.

*Figure 1  —  Three layers MACRO/MESO/MICRO with different trust and determinism characteristics.*

## 3.1. MACRO - Static workflow (deterministic, human-coded)

The macro process is written by humans: 'triage -> analyze -> approve -> remediate -> verify.' Order is known in advance, deterministic, replayable. This is where Temporal excels: workflow-as-code, durable execution, signals/timers/saga, retry policies.
Workflow code MUST be deterministic for Temporal to replay correctly. Non-deterministic operations (LLM calls, API calls, reading the clock) MUST be inside activities, not in workflow code. This is a hard rule.

## 3.2. MESO - Dynamic loop (AI intent, non-deterministic)

Within a single workflow step (e.g. 'analyze'), AI decides which tools to call, in what order, and how data flows between them. This ordering is dynamic and depends on actual results at each step. This layer consists of: LLM brain (untrusted) emitting parseable plans; a plan validator checking against schema/allow-list; state + ledger storing typed results for reference.
Critically: each AI decision = one separate Temporal activity, not stuffing the entire loop into one activity. This ensures each AI decision has individual durability + retry + audit. The workflow can still see and resume even if the orchestrator crashes.

## 3.3. MICRO - Broker + sandbox (enforcement, trusted)

The isolated execution layer. The broker (outside agent, inside agentd binary) resolves references to raw values, validates against capability manifest, executes via gVisor sandbox with JIT credentials, and returns typed results. This is where real enforcement happens - because the sandbox has no hardware-enforced boundary (no KVM), enforcement is pushed up to the broker.

## 3.4. Why separating three layers is itself a security property

- Each layer has its own appropriate language & tools: Python+Temporal (MACRO), tool-calling JSON schema (MESO), Go broker + runsc (MICRO).
- Clear trust gradient: MACRO trusted (written by humans), MESO untrusted (LLM), MICRO trusted (broker builds commands itself).
- Cross-layer attacks are blocked: prompt-injection in tool A output (MESO) cannot escalate to MACRO because macro is deterministic Python.

# 4. System Topology - Pull Model

AMOS deploys via pull: a centralized orchestration node; workers residing on target VMs (customer VMs) actively pull tasks out. This choice determines many important security properties.

*Figure 2  —  Pull model: target VMs only outbound mTLS; no inbound SSH needed, no KVM required.*

## 4.1. Push (SSH) vs Pull (worker loop) - choosing Pull

-> Pull is the default. SSH is only used for bootstrap (Ansible installs agentd once, with short-lived SSH certificate) or break-glass.

## 4.2. Control Plane components (Orchestration Node)

- **Temporal server ** —  workflow + DAG + durable state + signal/timer/saga.
- **Harness Registry ** —  versioned: guides, sensors, capability manifest, tool specs. Applied fleet-wide.
- **Identity & Policy ** —  mTLS (SPIFFE), short-lived credentials, OPA, Vault dynamic secrets.
- **Observability ** —  OpenTelemetry · Tempo · Loki · Prometheus · Grafana · immutable audit ledger.
- **Dashboard React ** —  fleet view, approval gate approvals, query/signal Temporal, audit replay.
- **Shared State Store ** —  Postgres (episodic), pgvector (semantic), Redis (working), S3/Swift (artifact).

# 5. agentd - Single Binary on Target VM

Only one static Go binary (named agentd) runs on each customer VM. This binary is internally divided into three clearly separated trusted roles plus a separate sandbox for the LLM brain outside the trust boundary.

*Figure 3  —  agentd internal structure: Supervisor + Broker + Sandbox Launcher (trusted) + gVisor sandbox (untrusted).*

## 5.1. Supervisor - Temporal worker

- Long-poll mTLS to orchestration node to receive activities (this is the pull mechanism).
- Verify Ed25519 signature on commands from control plane + nonce + expiry -> prevents replay/forgery.
- Supervisor tree in BEAM style: max-restart-intensity (too many restarts -> escalate instead of endlessly reviving).
- Budget enforcement (step/token/cost/cpu/time), dead-man timer.
- Runs non-root; narrow sudoers/systemd capabilities.

## 5.2. Broker - Policy Enforcement Point

- Loads signed capability manifest from Harness Registry; manifest is sealed - agent cannot modify it.
- Parses plan from LLM brain -> validates schema -> checks allow-list -> verifies arg constraints (regex/enum/range).
- Resolves references "${s1.x}" to real typed values from ledger; LLM never types raw values by hand.
- Run-count cap; idempotency dedup; goal predicate; taint sanitizer.
- Injects short-lived credentials from Vault just-in-time; LLM never sees raw secrets.
- Executes template on host; appends signed entry to ledger.
- Self-destructs when: goal reached / budget exhausted / TTL expired / anomaly detected.

## 5.3. Sandbox Launcher

- Calls runsc (gVisor systrap mode) per task - no KVM needed.
- Mounts minimal Wolfi rootfs: read-only, ephemeral, near-zero CVE, Sigstore signed.
- Applies: drop all caps, no_new_privs, seccomp, Landlock, userns map to unprivileged uid.
- Bind-mounts Unix socket /run/broker.sock into sandbox - the ONLY channel for brain to communicate with broker.
- Egress: TAP/veth + nftables host-side (sandbox cannot modify rules).
- Pluggable backend: if customer VM has /dev/kvm -> can switch to libkrun/Firecracker for stronger isolation.

# 6. Compute Substrate - Why gVisor

Design constraint: agent runs on any customer VM; no requirement to install KVM or enable nested virtualization. This is the gating condition that rules out true hardware microVMs.

## 6.1. Comparison of isolation options

## 6.2. gVisor systrap - technical detail

- Systrap has been gVisor's default platform since mid-2023, replacing ptrace. It uses seccomp to trap syscalls and route them into Sentry.
- Sentry is a kernel written in user-space that re-implements the Linux interface. Standard containers send syscalls directly to the host kernel; gVisor routes them through Sentry -> significantly reduces host kernel attack surface.
- runsc is an OCI-compatible runtime - can integrate with Docker/containerd/Kubernetes RuntimeClass when needed.
- Starts in a few milliseconds (no kernel boot), well-suited for high-frequency spawn-and-destroy workloads like agent tasks.

## 6.3. Tradeoffs to know

## 6.4. (Optional) Wolfi as rootfs

Wolfi (Chainguard) is a minimal undistro suited as the sandbox rootfs: built with apko/melange, signed with Sigstore, SBOM included, near-zero CVE. It achieves 'zero CVE' through five mechanisms working together: (1) extreme minimalism - no shell, no compiler, no package manager at runtime, reducing the attack surface to only what the agent needs; (2) aggressive patching - upstream release -> Wolfi package ready within ~4 hours; (3) single-version policy - only the latest version per package is maintained, no long tail of old versions accumulating CVEs; (4) rebuild from source - entire image reconstructed nightly, not just patching a top layer; (5) full automation - AI-driven reconciliation bots trigger dependency updates without manual intervention.
The 'zero CVE' claim means zero known CVEs at scan time, not immunity from zero-days. Practical implication for AMOS: set up a weekly CI rebuild job that pulls the latest Wolfi packages and fails the build if Grype reports any high/critical CVE. This maintains the Wolfi advantage over time.

# 7. Orchestration Layer (MACRO) - Temporal

Requirement: tasks with complex ordering, waiting on each other, resuming after crashes, policy-driven retries. This is exactly the durable workflow execution problem - already solved well. Building a custom DAG engine means spending months reinventing a worse Temporal.

## 7.1. Why Temporal

- **Workflow-as-code (Python/Go) ** —  write sequential flow normally; engine generates state machine automatically.
- **Durable execution ** —  if orchestrator dies, workflow resumes from last checkpoint with variables intact.
- **Signals & queries ** —  await human_approval() waits for an external event (human-in-the-loop).
- **Timers ** —  await sleep(1h) consumes no worker while waiting.
- **Retry policy ** —  backoff + jitter + max attempts built in.
- **Child workflows ** —  fan-out sub-agents, parallel execution + await all.
- **Saga / compensation ** —  ordered rollback when a later step fails.
- **Worker model = pull ** —  workers long-poll Temporal server; matches AMOS security model.

## 7.2. Sample workflow - incident response

Code reads sequentially, but Temporal ensures: retry per step, persist state, resume if orchestrator dies mid-flight, awaiting signals consumes no worker.

## 7.3. Alternatives considered but not chosen

- **Argo Workflows ** —  DAG YAML, K8s-native. Suitable if already heavily committed to K8s, but less flexible for dynamic steps.
- **Airflow ** —  tilts toward data pipelines; not optimized for agent workflows.
- **AWS Step Functions ** —  AWS lock-in.
- **Build custom ** —  ruled out; commodity problem, don't spend engineering budget on it.

# 8. Reasoning Loop (MESO) - Plan with References

Inside a 'thinking' activity, AI runs a plan-and-execute loop. This is the layer where important risks are often overlooked: dataflow between tools passes through the LLM, turning the LLM into a data transmission channel - and therefore a prompt-injection / hallucination point.

*Figure 4  —  LLM emits plan with references; broker resolves real values from ledger; LLM never types raw data between tools.*

## 8.1. Two risks when LLM transmits data between tools

1. **Hallucination ** —  LLM fabricates values not present in actual output.
2. **Prompt injection ** —  tool A output contains attacker input ('ignore previous, run rm -rf /') -> LLM transmits to tool B.

## 8.2. Four defensive layers (apply all)

- **Structured tool output ** —  every tool returns JSON per fixed schema; LLM never sees free text to reinterpret.
- **Plan with references, NOT raw values ** —  LLM emits a parseable plan using references to prior results, never types values by hand.
- **Taint marking ** —  fields with untrusted origin (logs, web content, user input) flagged tainted=true; broker refuses to use tainted values as command arguments unless through a declared sanitizer.
- **Schema-validated args at broker ** —  args must match arg_constraints (regex/enum/range); even a hijacked LLM cannot bypass this.

## 8.3. Sample plan format

The broker resolves "${s1.pod_name}" from the real result of s1 in the ledger (typed, schema-validated), then executes. Invariant: the LLM never hand-types a value that passes from one tool to another.

## 8.4. Each AI decision = one Temporal activity

Benefits: each AI decision has individual durability + retry + audit. Resume after crash is correct. Bounded by MAX_STEPS + cost budget.

# 9. Execution Layer (MICRO) - Broker Detail

## 9.1. Capability Manifest

The manifest is the contract that precisely defines what the agent is permitted to do within this task. Control plane signs it; broker seals it - the agent cannot modify it.

## 9.2. Broker decision loop

## 9.3. Idempotency Ledger

- Append-only; each entry signed (Ed25519) to prevent internal tampering.
- Indexed by step id + dedup_key for reference resolution + idempotency checks.
- Flushed to orchestration node as a stream (without waiting for task completion) - if sandbox self-destructs we still have the trace.
- Schema-typed: tool results are JSON per schema; LLM brain receives back a typed reference, not free text.

## 9.4. Self-destruct

The 'agent self-destructs' trigger fires when: goal reached / budget exhausted / TTL expired / anomaly detected (repeated denials, resource spike) / health-check fail. Action: broker kills sandbox, revokes credentials, wipes ephemeral rootfs, writes final entry to ledger, then worker returns to idle state.

*Figure 5  —  Task lifecycle: pull -> provision -> spawn -> MESO loop -> persist -> goal check -> terminate.*

# 10. Security Model - Two Boundaries + Five Layers

## 10.1. Two boundaries

### Boundary A - Control plane ↔ Target VM

- **Pre-installed supervisor ** —  instead of static root SSH, install agentd via Ansible bootstrap with SPIFFE identity; orchestrator -> agentd via mTLS gRPC.
- **SSH only for bootstrap ** —  use short-lived SSH certificate (CA-signed) + force-command + source-address; no static key.
- **Signed commands ** —  each instruction from control plane signed Ed25519, with nonce + expiry; supervisor verifies against pinned public key before forwarding to broker.
- **Binary integrity ** —  agentd signed via cosign/Sigstore; hash verified before execution; reproducible build from Wolfi.

### Boundary B - Agent ↔ external world

- **Egress deny-by-default ** —  nftables at TAP/veth host-side; only open exact endpoints in egress_allow; DNS pinned.
- **Credential proxy ** —  strips credentials from outbound traffic; agent sees URL, never token (Cleanroom model).
- **Credentials never in sandbox ** —  broker injects secrets JIT for exactly one approved command (Vault dynamic).
- **No host FS mount ** —  sandbox has no bind mount to host; all host actions go through broker RPC.
- **Defense-in-depth inside guest ** —  seccomp · Landlock · no_new_privs · drop all caps · rootfs read-only · userns.

## 10.2. Five layers + threat model

*Figure 6  —  Five defensive layers (left) and threat model  —  if component X is compromised (right).*
1. **L1  —  Isolation: **gVisor Sentry (userspace kernel) + seccomp; no KVM needed.
2. **L2  —  Kernel policy inside guest: **seccomp + Landlock + no_new_privs + drop all caps; Wolfi rootfs read-only.
3. **L3  —  Network egress allow-list: **nftables host-TAP side; sandbox cannot modify rules.
4. **L4  —  Capability token + manifest: **scoped to this task; Vault dynamic, short TTL; arg constraints + allow-list + run-count cap.
5. **L5  —  Human approval gate: **all destructive actions require dashboard approval with dry-run diff.

# 11. Observability & Audit

Because sandboxes are ephemeral, observability MUST be streaming and externalized: telemetry leaves the sandbox immediately, without waiting for the task to complete (if we wait, sandbox destruction means losing the trace).
- **Traces ** —  each tool call is a span (tool_name, input_hash, latency, status, token_cost). Exported via OpenTelemetry -> Tempo.
- **Logs ** —  structured logs tagged with task_id, pushed to Loki; forwarder/sidecar runs outside sandbox.
- **Metrics ** —  cold-start, step count, tokens/task, sensor pass rate, deny rate, runtime cost -> Prometheus/Grafana.
- **Audit ledger ** —  who/what/when/result/signature; serves compliance + root-cause analysis.

# 12. Harness Engineering Loop

This is the mechanism that transforms AMOS from 'it runs' to 'it is reliably trustworthy over time.' Each mistake is not just fixed for this instance, but converted into a structural constraint in the Harness Registry, applied fleet-wide.
1. Agent runs task in sandbox.
2. Mistake detected by sensor, audit, or human.
3. Root-cause analysis: why was this mistake possible?
4. Engineer a permanent fix - new guide / new sensor / tighten arg constraint / tighten allow-list / add taint rule.
5. Update Harness Registry (versioned) -> applied to all future tasks.
Classify fixes into three layers: context (add knowledge/runbook), architectural constraint (add deterministic linter/structural test), and garbage-collection agent (runs periodically to clean up inconsistencies, resist entropy).

# 13. Technology Stack - Complete Reference

# 14. End-to-End Reference Workflow

A real incident: alert 'CPU > 90% on node-03' flowing through all three layers.

### MACRO layer (Temporal workflow)

1. Alertmanager fires webhook -> Temporal starts IncidentResponse workflow.
2. Workflow runs collect_metrics(node) in parallel with analyze_logs(node).
3. Workflow calls activity propose_remediation -> this is where the MESO loop runs.
4. Workflow awaits workflow.wait_signal('approve', timeout=10min) - L5 gate.
5. If approved -> activity remediate; then verify_healthy; on failure -> rollback + page_oncall.

### MESO layer (inside the propose_remediation activity)

1. Worker (agentd) on node-03 receives activity, verifies command signature.
2. Sandbox launcher starts runsc with Wolfi rootfs + manifest for this task.
3. LLM brain emits plan: [s1 = get_processes, s2 = get_pod_status(args from s1), s3 = propose].
4. Each step is a separate Temporal activity -> durable.

### MICRO layer (broker)

1. Broker receives plan via Unix socket -> validates schema, allow-list, arg constraints.
2. Resolves references: '${s1.top_pod}' -> 'nginx-7f' (typed, untainted, schema-passed).
3. Injects Vault creds JIT, executes template on host, returns typed result, appends to ledger.
4. Plan finally returns 'restart pod nginx-7f' (mutating) -> requires L5 approval.
5. After approval + remediation complete, sandbox self-destructs (goal reached + budget exhausted).

# 15. Comparison with Adjacent Platforms

## 15.1. AWS Bedrock AgentCore Runtime

AgentCore is a managed isolation substrate on AWS: each user session gets a Firecracker microVM with isolated CPU/memory/FS; after the session, the entire microVM is destroyed + memory sanitized. This **closely matches the 'ephemeral substrate' tier that AMOS designs**, packaged as a service.
Key difference: AgentCore documentation states clearly that 'the isolation boundary is the microVM itself' - inside, the agent has full FS + credential access. AMOS adds a BROKER OUTSIDE THE AGENT layer to enforce the inner boundary, plus capability manifest + idempotency ledger + goal-based self-destruct.

A sensible combination: if running on AWS, use AgentCore as the substrate then place AMOS's broker inside. If the goal is running on any customer VM, AMOS builds both layers itself.

## 15.2. Claude Dynamic Workflows (Anthropic, 28 May 2026)

Dynamic Workflows is a research-preview feature in Claude Code: Claude writes a JavaScript orchestration script for a task you describe; the runtime executes the script in the background, capable of spawning up to ~1000 subagents in parallel. Intermediate results live in script variables so they don't fill up the context window. It essentially productizes the orchestrator-workers pattern from 'Building effective agents.'
**Very closely related to AMOS** - both use the 'AI writes plan, executor runs plan' pattern. Real differences:

Correct framing: Dynamic Workflows is one possible implementation of the MESO layer in AMOS. You **can call DW (via MCP) from inside a Temporal activity**. But **DW does not replace MACRO** (Temporal: signals, multi-day durability) **and does not replace MICRO** (broker enforcement on the customer VM).

# 16. Implementation Roadmap

Recommendation: start narrow with 1-2 read-mostly SysOps task types (triage, health-check) for P0-P2; prove value; then gradually expand to mutating actions with approval.

# 17. Risks & Caveats

- **gVisor not HW-enforced ** —  against an attacker actively trying to escape, a microVM is stronger. Compensate with broker outside + non-root + seccomp/Landlock.
- **gVisor syscall compatibility ** —  does not cover 100% of Linux syscalls. Test early with Wolfi rootfs + Python LLM client.
- **Losing traces when sandbox terminates quickly ** —  streaming telemetry externalization is mandatory; if you wait until task completion to flush, sandbox destruction means data loss.
- **Over-automation ** —  destructive actions must go through L5 approval; start with read-mostly workloads, expand permissions gradually.
- **Prompt injection into tool output ** —  taint marking + sanitizer + arg constraints are the main defense; never trust LLM alone.
- **Bootstrap risk ** —  short-lived SSH cert only for initial agentd installation; disable inbound SSH completely thereafter.
- **Temporal lock-in ** —  significant dependency but OSS + self-hostable; ROI is clear vs building a custom engine.

# 18. 2026 Landscape & Architecture Optimization by Phase

After surveying similar solutions active in late Q1/2026, we adjust the implementation roadmap to align with patterns that have converged in the industry, divided into three phases - the first deliberately simple and low-technology to ship a working product quickly.

## 18.1. Survey - three active areas

### Sandbox runners for agents

The landscape has clearly differentiated. E2B leads with 200M+ sandboxes and Fortune 100 customers (Firecracker, Apache-2.0 open-source). Microsandbox (YC X26, ~5K GitHub stars) is the ONLY local-first microVM platform, using libkrun, with network-layer secret injection preventing credential leakage by-design. Daytona achieves 90ms cold-start with Computer Use support, raised $24M Series A in Feb 2026. Sprites (Fly.io) challenges the ephemeral model with persistent VM + instant checkpoint/restore. Northflank BYOC allows choosing Kata + Cloud Hypervisor / gVisor / Firecracker. OpenSandbox (Alibaba) takes a protocol-driven, multi-language SDK, K8s-native approach. Zeroboot achieves 0.79ms cold-start via copy-on-write. Modal excels for GPU workloads.
Key observation: none of these platforms target SysOps on arbitrary customer VMs with the constraint of no KVM - the majority are sandbox-as-a-service for coding agents on cloud SaaS. This is AMOS's differentiated market position.

### Dataflow security - CaMeL by DeepMind

CaMeL (Capabilities for Machine Learning, DeepMind, paper 03/2025) is the research-grade formalization of the 'plan with references' pattern that AMOS uses. Every value carries metadata (capability) constraining data and control flow; the LLM becomes a 'compiler' emitting restricted DSL (Python subset) rather than free-form commands; a deterministic interpreter runs the plan. Draws inspiration from traditional Control Flow Integrity + Access Control + Information Flow Control.
Results: solves 67% of AgentDojo benchmark with provable security, near-100% block rate for prompt injection in other evaluations. Tradeoff: utility from 84% to 77%. An operationalization paper (Tallam & Miller, 07/2025) proposes four improvements: prompt screening, output auditing, tiered-risk access model, formally verifiable intermediate language. A version for Computer Use Agents was released 03/2026.

### Orchestration - two-layer Temporal + LangGraph is now standard

Temporal raised $300M at $5B valuation (02/2026); 9.1 trillion lifetime executions at 380% YoY growth; OpenAI runs Codex on Temporal handling millions of agent requests per day. OpenAI Agents SDK ↔ Temporal integration GA in 03/2026. LangGraph 1.0 (10/2025) became the standard for agent control flow with PostgreSQL checkpointing. The two-layer pattern has clearly won: LangGraph handles reasoning at the micro level, Temporal handles durable execution at the macro level.

## 18.2. Four converged patterns

1. Two-layer orchestration (durable macro + flexible agent loop) is production baseline, no longer 'advanced.'
2. Dataflow security via capability + Information Flow Control is the only provably prompt-injection-safe approach (CaMeL).
3. Sandbox is the backend; protocol is the interface - pluggable runtime (gVisor / libkrun / Firecracker / Kata) behind a common interface.
4. Secret never in sandbox - Microsandbox leads with network-layer injection; sandbox never holds tokens, not even for 1ms.

## 18.3. Three-phase roadmap

## 18.4. Phase 1 - MVP 'Agent in a gVisor box'

Single goal: prove that an LLM agent can run in a gVisor sandbox on a customer VM, call tools in the allow-list, and cannot execute arbitrary commands even if the LLM brain is fully compromised. Ship in 4-6 weeks with 1 engineer.

### 18.4.1. What's IN vs OUT for P1

### 18.4.2. Packaging agent into gVisor - detail

*Figure 7  —  Phase 1: three build-time artifacts (left) + runtime topology on customer VM (right).*

### Artifact 1 - agentd binary

### Artifact 2 - Wolfi rootfs (via apko)

### Artifact 3 - Capability manifest (YAML per task)

### 18.4.3. runsc invocation and OCI bundle

### 18.4.4. Agent loop inside sandbox (plain Python, no LangGraph)

### 18.4.5. Control plane MVP (HTTP, no Temporal)

### 18.4.6. P1 security baseline

Despite being minimal, P1 has these core security properties (already better than plain Docker):
- gVisor Sentry syscall isolation - host kernel not directly exposed.
- Broker outside agent - LLM brain has no shell on host, can only emit requests via Unix socket.
- Static tool allow-list - no tool outside the manifest can run.
- Simple plan-with-references - LLM cannot hand-type raw values between tools.
- Read-only ephemeral rootfs - attacker has no way to 'persist' in sandbox.
- Non-root (uid 65532) inside sandbox + agentd also non-root on host.
- Egress allow-list via nftables host-side - sandbox cannot modify.
- mTLS control plane ↔ agentd - no inbound SSH to customer VM.
- Append-only ledger - every action has an audit trail.

### 18.4.7. Phase 1 deliverables

1. agentd binary built for Linux x86_64 (Go).
2. apko config + build script for rootfs.img (Wolfi base + Python agent).
3. Control plane FastAPI with 5 endpoints, state stored in Postgres/file.
4. Ansible playbook to bootstrap agentd onto 1 customer VM (via short-lived SSH cert).
5. Manifest for 5-10 initial read-only SysOps tools (get_pod, get_logs, get_metrics, list_services, health_check…).
6. End-to-end test: 1 incident triage task running from control plane -> agentd -> sandbox -> result.
7. Operations documentation: installation, troubleshooting, audit ledger format.

## 18.6. Phase 2 - Production durability

Once P1 proves feasibility, P2 upgrades to production-grade. Four change groups:

### 18.6.1. Replace HTTP poll with Temporal worker

Migrate control plane from 'manual HTTP loop' to Temporal server. Each agentd becomes a Temporal worker (long-poll is essentially the same mechanism, but using the standard gRPC protocol). Benefits: durable execution, retry policy, signal/timer/saga, multi-day workflows, multi-step chains without manual Python scripts.
Python workflow code replaces the P1 script; each run_task() becomes an activity. Saga compensation and human-in-the-loop signals are built in.

### 18.6.2. Identity + secrets done properly

- **SPIFFE/SPIRE ** —  identity for agentd; mTLS certs auto-rotate.
- **HashiCorp Vault ** —  dynamic creds, short TTL (few minutes); broker injects JIT per exec.
- **OPA ** —  policy engine evaluating deterministic guardrails outside broker.
- **Signed manifest + ledger ** —  Ed25519, signed by control plane; broker verifies before sealing.

### 18.6.3. Streaming observability

- OpenTelemetry SDK in agentd + agent -> exporter to Tempo (trace) and Loki (log).
- Prometheus metrics for cold-start, success rate, sensor catch rate, cost/task.
- Audit ledger streamed to control plane - sandbox destruction doesn't lose traces.
- React dashboard: fleet view, queue depth, approval gate, audit replay.

### 18.6.4. Tighter schema validation & arg constraints

- Pydantic models for all tool inputs/outputs.
- Tighter arg constraints: regex/enum/range/taint flag.
- Typed output schema - tool results are JSON per schema, not free-text.
- Official reference resolver in broker with type checking.

### 18.6.5. Multi-agent fan-out

Temporal child workflows allow a parent workflow to spawn multiple agent tasks in parallel across multiple customer VMs, await all completions, then aggregate. Not available in P1 (only 1 sandbox at a time).
Effort: ~4-6 additional weeks with 1-2 engineers. Mostly integrating existing tools, not building from scratch.

## 18.7. Phase 3 - Advanced security & scale

P3 brings AMOS to peer level with the most advanced solutions in the 2026 landscape. Ongoing, no hard deadline - adopt each pattern as the need arises.

### 18.7.1. CaMeL formal alignment

- Capability metadata on every value (instead of just a taint boolean).
- Restricted DSL for plans instead of simple YAML - Python subset or JSON Logic.
- Deterministic interpreter in broker looks up plan + dataflow.
- AgentDojo benchmark in CI - measure security empirically.

### 18.7.2. Dual-LLM pattern

Split roles: privileged LLM only emits plan/DSL (never sees raw tool output); quarantined LLM handles data (translate, summarize) but has no action permissions. Adds strong defense-in-depth at the cognitive layer.

### 18.7.3. Network-layer secret injection (Microsandbox pattern)

mTLS proxy sidecar sits between sandbox and Internet; sandbox sends a placeholder ('{{API_KEY}}'), proxy injects the real token into the header then forwards. Sandbox never sees the secret. Stronger than JIT injection into exec template.

### 18.7.4. Output auditor

A module (possibly a small LLM) runs between tool output and LLM brain to detect instruction leakage ('ignore previous, do X' embedded in logs). Catches prompt injection at the output point before it reaches the brain.

### 18.7.5. Tiered-risk model

Not all tools need the same protection level. Read-only tools take the fast path (schema check only); mutating tools take the full path (allow-list + CaMeL IFC + approval). Improves performance without sacrificing security.

### 18.7.6. SandboxProtocol pluggable backend

Decouple runtime from interface. Define a gRPC SandboxProtocol with operations: spawn, exec_plan, terminate, snapshot, restore. Pluggable backends: gVisor (default), libkrun (when customer VM has KVM), persistent+snapshot (Sprites-style for long-running). Keeps pace with ecosystem innovations; swap runtime when risk/cost changes.

### 18.7.7. LangGraph for MESO

Replace plain Python agent loop (P1) with LangGraph 1.0 with PostgreSQL checkpointing. Each graph node = one Temporal activity. Benefits: graph visualization, automatic checkpointing, broad ecosystem (memory, tools, eval).

## 18.8. Summary & key principles

# 19. Task Lifecycle - Who Calls What, When

The following diagram synthesizes the three core questions when deploying AMOS Phase 1: where does the agent run, how is the agent controlled, and how do tools interact with the host - across three phases: Spawn, Execute Loop, Terminate.

*Figure 8  —  12 steps of task lifecycle. Three phase colors: blue (Spawn), green (Execute loop), orange (Terminate).*

## 15.1. Spawn phase - manifest is the only way to send commands to agent

- **Step 1 ** —  agentd long-polls control plane via mTLS. Receives task + manifest (Ed25519-signed payload). This is how the control plane 'commands' the agent - there is no two-way RPC into a running agent.
- **Step 2 ** —  agentd calls 'runsc run task-id' with OCI bundle. Bundle mounts two things into sandbox: manifest.yaml (read-only) and broker.sock. No host FS mount, no credential mount.
- **Step 3 ** —  Sandbox starts, agent reads /etc/manifest.yaml, knows goal + budget + permitted tool list. Opens /run/broker.sock - the only channel out to host.

## 15.2. Execute loop phase - broker is the one who actually runs commands

- **Steps 4 — 5 ** —  Agent calls LLM API via the only permitted egress channel (nftables allow-list on host). Receives structured plan JSON.
- **Step 6 ** —  Agent sends request via Unix socket (JSON: tool, args, step_id). This is how the agent 'calls a tool' - not direct exec, no kubectl in sandbox rootfs.
- **Step 7 ** —  Broker (inside agentd, outside sandbox) validates: tool ∈ allow-list? args match arg_constraints? runs < max_runs? resolve ${refs} from ledger? If any condition fails -> deny immediately, no exec.
- **Steps 8 — 9 ** —  Broker execs template on HOST (not inside sandbox) with broker's own credentials. kubectl/helm/ansible run here, with broker's KUBECONFIG/token, never exposed to agent.
- **Step 10 ** —  Broker returns typed result via same socket, simultaneously appending a signed entry to the ledger. Agent receives result, updates state, emits next plan.

## 15.3. Terminate phase - no residual state

- **Step 11 ** —  Two paths: agent exits naturally (goal reached) or agentd calls 'runsc kill SIGTERM' (TTL/budget). Sentry receives signal -> sends to PID 1 -> sandbox destroyed -> ephemeral rootfs wiped clean.
- **Step 12 ** —  agentd: revoke credentials, wipe socket, flush ledger to control plane, send POST /report, return to idle state ready for next task.
After terminate: no process on host belonging to that task. No socket. No credentials. No state on rootfs (wiped). All trace lives only in the ledger on the control plane.

# References

1. Mitchell Hashimoto - My AI Adoption Journey (Feb 2026): mitchellh.com/writing/my-ai-adoption-journey
2. OpenAI (Ryan Lopopolo) - Harness engineering: leveraging Codex in an agent-first world (Feb 2026)
3. Anthropic - Building effective agents (Dec 2024): anthropic.com/research/building-effective-agents
4. Anthropic - Effective Harnesses for Long-Running Agents (Nov 2025)
5. Anthropic Claude Code Docs - Orchestrate subagents at scale with dynamic workflows (May 2026)
6. Martin Fowler / Birgitta Böckeler - Harness Engineering memo: martinfowler.com
7. gVisor - Platform Guide & Systrap release notes: gvisor.dev/docs/architecture_guide/platforms
8. Northflank - Kata vs gVisor; Cloud Hypervisor vs gVisor; What is gVisor (2026)
9. Northflank - Self-hostable alternatives to E2B / Daytona for AI agents (Feb 2026)
10. Chainguard Academy - How Chainguard creates zero-CVE images; Wolfi undistro: chainguard.dev
11. AWS - Security best practices for AgentCore Runtime: docs.aws.amazon.com/bedrock-agentcore
12. Temporal - Workflow patterns, Python SDK: docs.temporal.io
13. Ry Walker - AI Agent Sandboxes Compared 2026 (E2B, Microsandbox, Sprites, Daytona, Modal...)
14. Microsandbox (YC X26) - libkrun-based local-first microVM with network-layer secret injection
15. DeepMind - CaMeL: Defeating Prompt Injections by Design (arXiv 2503.18813, Mar 2025)
16. Tallam & Miller - Operationalizing CaMeL (arXiv 2505.22852, Jul 2025)
17. Foerster et al. - CaMeLs Can Use Computers Too (arXiv 2601.09923, Mar 2026)
18. AgentDojo - Adversarial benchmark for agent security (NeurIPS 2024)
19. AgentMarketCap - LangGraph vs Temporal for Long-Running Agent Workflows: 2026 Decision Guide
20. SPIFFE/SPIRE - Workload identity: spiffe.io
21. HashiCorp Vault - Dynamic secrets: vaultproject.io
22. OpenHarness (HKUDS) and Hermes-agent (NousResearch) - agent reference implementations