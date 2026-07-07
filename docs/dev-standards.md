# Dev standards (Python services)

How the cluster's Python services are developed and shipped: lint / typecheck / test
conventions plus the Docker baseline. Applies to `ludo-agent`, `ludo-gateway`,
`ludo-cli` (webapps backend is retiring). Canonical ruff config:
[`../templates/ruff.toml`](../templates/ruff.toml); baseline values in
`cluster.yaml:tooling`. Not to be confused with agent tools — those are
[`tools.md`](tools.md).

## Tooling

| Concern | Standard |
|---|---|
| Python | **3.12** (`requires-python = ">=3.12"`; agent pins `<3.13`) |
| Package manager | **uv** (`uv sync`, `uv run`) |
| Ruff line-length | **120** (cluster standard; gateway moved 110→120 — widening adds no E501s) |
| Ruff target | `py312` |
| Ruff select — **core** (clients: gateway, cli) | `E, F, I, UP, B` + bugbear `extend-immutable-calls` for FastAPI DI |
| Ruff select — **engine** (agent) | core + `W, C4, SIM, RUF, ASYNC`, `ignore = E501` (autonomy-bar discipline) |
| mypy | **strict** for the engine (agent) + cli; lighter/absent for gateway today — standardize to strict (follow-up) |
| Tests | pytest; agent + gateway have `make`/CI (`ruff check . && pytest -q`); webapps tests run in isolated `tests/venv/` |

**Two tiers, on purpose:** the agent is the autonomy engine and runs the stricter `engine` lint +
strict mypy; clients run `core`. Don't homogenize away the engine's extra rules.

To adopt: copy `templates/ruff.toml` into the repo's `pyproject.toml` `[tool.ruff]` (engine extends
`select`). Keep line-length 120 everywhere.

## Docker baseline

Conventions for the containerized Python services (agent, gateway).

- **Base image:** `python:3.12-slim` (`cluster.yaml:tooling.docker_base`).
- **Non-root:** run as a dedicated unprivileged user (the agent uses `uid 10000`, group `ludo`,
  home `/home/ludo`). Adopt the same for the gateway image (dev stages may run root; prod should not).
- **Deps:** install via `uv` (`uv sync`/`uv pip install`); `PYTHONDONTWRITEBYTECODE=1`,
  `PYTHONUNBUFFERED=1`. Don't bake source as a volume in prod — build into the image.
- **node_modules / venv stay out of images** (house rule) — built/mounted, not committed.
- **One concern per container:** agent = `app` + `minio`; gateway = `gateway` + `nats`; each store
  is its own container, never shared (three-stores rule). DB volumes:
  gateway `/srv/data`, agent `/data` + `/app/memory`, webapps `/app/data/sqlite`.
- **Stateful caveat:** single-writer SQLite (ADR 0001) → one writer replica owns the data volume;
  scale reads with stateless replicas. See [`db-conventions.md`](db-conventions.md).

Ports + addressing: [`network-and-ports.md`](network-and-ports.md). Build commands stay per-repo
(the user runs Docker builds on CLI).
