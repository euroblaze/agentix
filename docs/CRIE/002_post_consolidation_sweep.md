# CRIE 002 — post-consolidation cluster sweep

Date: 2026-06-26. Scope: all 6 repos. Follows CRIE 001 (ludo_shared Python consolidation).
Index issue: euroblaze/ludo-init#11. Method: 3 parallel repo sweeps vs the 001 baseline
(reports only new / still-open items), high-signal findings spot-verified against source.

## Repo -> slug
| dir | slug |
|---|---|
| ludo-agent | euroblaze/ludo |
| ludo-gateway | euroblaze/ludo-gateway |
| ludo-cli | euroblaze/ludo-omg |
| ludo-desktop | euroblaze/ludo-desktop |
| ludo-init | euroblaze/ludo-init |
| ludo-webapps | euroblaze/ludo-flywheel (-> ludo-webapps) |

## Baseline carried from 001 (verified resolved — not re-reported)
- `ludo_shared` (types + broker constants + SSE codec) generated in hub, vendored into
  agent/gateway/cli. Drift guard `check_shared_drift.py`. (PRs still open — see T0.)
- Licenses: agent/gateway/webapps Proprietary; cli/desktop BSL public; hub BSL private.
- Desktop SSE parser fixed (was NDJSON) — fix currently staged, uncommitted.
- R-1 gateway<->webapps parallel control-plane: intentional strangler-fig (flywheel#96), no action.

---

## Themes

### T0 — Land in-flight work (prerequisite, no new code) -> #10
4 open `ludo_shared` PRs (init #7, omg #6, gateway #26, agent #515); staged desktop
`LiveAPIClient.swift`; init `CLAUDE.md` + untracked `docs/proposals/tool-skill-calling.md`
(#503 refactor, same proposal staged in agent). Land these first.

### T1 — Codegen expansion (IE-1 remainder) — biggest lever, P0 -> #8
Python types are generated; TS + Swift are hand-written -> silent drift.
- `ludo-webapps/backend/app/services/notifications.py:21` + `libs/shared/migration_states.js:6`
  — `MIGRATION_STATES` hand-synced py<->js. -> euroblaze/ludo-webapps#101
- `ludo-desktop` `Models/Live.swift:31` — `MigrationState` enum + DTOs hand-kept; events as raw
  `String`. -> euroblaze/ludo-desktop#4
- Hub fix: `scripts/gen_ts.py` + `gen_swift.py` emit types + enums (incl. `MIGRATION_STATES`)
  from `contracts/` + `cluster.yaml`; vendor + drift-guard. Retires R-5a / Swift dup / IE-5.

### T2 — Client know-how docs (IE-3) — P1 -> #9
`docs/contracts-consumer-guide.md` is thin. Consolidate: PKCE flow (S256), client-config
convention (env names, base-URL from `cluster.yaml`, token-storage tiers), SSE resumption
(`Last-Event-ID`/seq), retry/backoff, error taxonomy. Aligns gateway PKCE #30, desktop
base-URL #5, omg retry (ludo-omg #7).

### T3 — Locale reconciliation (C-3, still open) — P1
`cluster.yaml` `backend_default: "de"` / `frontend_default: "en"` vs hardcoded `"en"`:
- gateway `backend/app/models.py:44` `Account.locale default="en"` + `seed.py`. -> euroblaze/ludo-gateway#27
- webapps `backend/app/config.py:98`, `db.py:64,181`. -> euroblaze/ludo-webapps#102
Derive from cluster.yaml; decide the account default explicitly.

### T4 — Per-repo internal dedup & correctness
agent (euroblaze/ludo):
- `_chunk()` duplicated ×6 (tools: load_attachments, rollback, sync_pinned_fields,
  invoke_workflow_action, extract_binary, restore_workflow_states); `_deferred_fk_key()` ×2
  (`tools/load_to_odoo.py:330`, `tools/relink_deferred.py:48`). -> euroblaze/ludo-agent#517
- naive `datetime.now()` (cli/workflow_restoration.py:123,197; actions/verify_customer.py:198,341;
  actions/estimate.py:128) + deprecated `datetime.utcnow()` (actions/port_module.py:468)
  -> `datetime.now(UTC)`. -> euroblaze/ludo-agent#518

gateway:
- `/system/status` registered twice (`routers/health.py:13` AND `routers/system.py:9`, both
  un-prefixed in main.py — last wins); `"not found"` strings repeated (migrations.py:34,49,64;
  events.py:22). -> euroblaze/ludo-gateway#28
- hand-rolled dict projections (store.py:36-45, commerce.py:24-25,152-154) + request models
  without Field/Literal constraints (auth/commerce Req classes). -> euroblaze/ludo-gateway#29

### T5 — Doc freshness / correctness
- agent `README.md:63` says "MIT" but LICENSE is Proprietary; README still describes `omg` as
  shipping here (now `euroblaze/ludo-omg`). -> euroblaze/ludo-agent#516
- webapps `.claude/CLAUDE.md:32`: "schemas live in ludo-gateway/contracts" — canonical is
  `ludo-init/contracts`. -> euroblaze/ludo-webapps#103
- gateway `routers/commerce.py:61` returns 401 for missing `account_id` (caller IS auth'd) —
  should be 403/422. -> euroblaze/ludo-gateway#31

---

## Deferred (tracked, not actioned this pass)
- IE-2b internal NATS `Broker` client relocation to a private-only shared home (agent<->gateway).
- Gateway test-coverage expansion — held under the defer-tests-during-build-out rule.
- webapps TypeScript adoption — design choice; only relevant once T1 lands.

## Realized — Batch A (independent quick wins, merged 2026-06-26)

Tracking fixes first: desktop #4 reopened (only item 1 shipped), #10 closed (T0 complete),
flywheel#41 closed as dup of #101. Then 8 issues across 3 PRs:
- ludo (agent) PR #520 — #516, #517, #518
- ludo-gateway PR #32 — #27, #28, #31
- ludo-webapps PR #104 — #102, #103

**Honest code-savings accounting.** Batch A was mostly *correctness + docs*, not deletion.
Genuine redundancy removed:

| Item | Before | After | Code refs |
|---|---|---|---|
| `_chunk` (agent #517) | 6 identical copies (~12 lines) | 1 canonical `tools/_batch.chunk` | `src/ludo/tools/_batch.py`; was in load_attachments/rollback/sync_pinned_fields/invoke_workflow_action/extract_binary/restore_workflow_states |
| `_deferred_fk_key` (agent #517) | 2 identical copies (~5 lines) | 1 canonical `tools/_keys.deferred_fk_key` | `src/ludo/tools/_keys.py`; was in load_to_odoo + relink_deferred |
| `/system/status` (gateway #28) | registered twice | once (canonical) | `backend/app/routers/{health,system}.py` |
| `"not found"` literals (gateway #28) | 4 inline copies | 1 `errors.NOT_FOUND` | `backend/app/errors.py` |

**Duplication count: 9 redundant sites → 2 canonical helpers + 1 route + 1 const module.**
**Net LOC ≈ flat** (agent commit was 46 ins / 48 del = −2): the removed duplicate logic (~17
lines) is offset by the two small helper files' docstrings/headers + 8 one-line import aliases.
The gateway commerce.py "+153" is almost entirely `ruff format` reflow of pre-existing dict
literals — only 3 lines are real (401→403 + import); excluded from the count above.

The value is the **maintenance win** (a chunking/key-format change now touches 1 file, not 6/2),
not line reduction. The actual cross-language LOC savings land in **Batch B (#8 codegen)** — that
deletes `migration_states.js` + the `MIGRATION_STATES` py↔js hand-sync and the desktop
hand-maintained Swift enum/DTOs.

Correctness/doc items (zero LOC savings): #516 README license, #518 UTC datetimes (4 sites),
#31 401→403 semantics, #27/#102 locale anchoring to cluster.yaml, #103 contracts-source doc.

## Issue index (17 sub-issues under euroblaze/ludo-init#11)
| # | Repo | Issue | Theme | Pri |
|---|---|---|---|---|
| 1 | ludo-init | #8 codegen TS/Swift | T1 | P0 |
| 2 | ludo-init | #9 client know-how docs | T2 | P1 |
| 3 | ludo-init | #10 land in-flight | T0 | P1 |
| 4 | ludo-webapps | #101 MIGRATION_STATES | T1 | P1 |
| 5 | ludo-webapps | #102 locale | T3 | P1 |
| 6 | ludo-webapps | #103 CLAUDE contracts loc | T5 | P1 |
| 7 | ludo-desktop | #4 Swift DTOs + SSE commit | T1/T0 | P0 |
| 8 | ludo-desktop | #5 base-URL config | T2 | P1 |
| 9 | ludo-gateway | #27 locale | T3 | P1 |
| 10 | ludo-gateway | #28 dup /system/status + errors | T4 | P1 |
| 11 | ludo-gateway | #29 response_model + constraints | T4 | P2 |
| 12 | ludo-gateway | #30 PKCE real verify | T2 | P1 |
| 13 | ludo-gateway | #31 checkout 401->403/422 | T5 | P2 |
| 14 | ludo (agent) | #516 README license | T5 | P0 |
| 15 | ludo (agent) | #517 dedup helpers | T4 | P1 |
| 16 | ludo (agent) | #518 datetime UTC | T4 | P1 |
| 17 | ludo-omg | #7 retry/backoff | T2 | P2 |
