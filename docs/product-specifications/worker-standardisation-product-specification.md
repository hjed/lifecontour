# Worker Standardisation Product Specification

## Overview

This document defines the target product behaviour for standardising the system's integration
workers. It is a product specification rather than a technical design.

The system currently runs four integration workers under `integration_workers/` — `google`,
`immich`, `strava`, and `snipeit`. Each was built incrementally and they have drifted apart: settings
are declared differently and partly duplicated, ARQ worker configuration and lifecycle code is
hand-written per worker with divergent values, and fan-out (batch) jobs block a worker slot for their
entire duration. The result is that creating a new worker means copying an existing one and
re-deriving conventions, and that long fan-outs consume scarce worker concurrency while idle.

This specification builds on the event architecture already established in
`docs/product-specifications/integration-architecture-and-strava-product-specification.md` (domain
events flow over a Redis Streams event bus via the transactional outbox). It does not change that
architecture; it refines the per-worker conventions and consolidates shared concerns into the
existing `core_shared` package. Where existing worker implementations conflict with this
specification, this specification takes precedence and the workers should be migrated to it.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/architecture/integration-architecture.md`
- `docs/architecture/database-design.md` (transaction management, commit-as-you-go)
- `docs/product-specifications/integration-architecture-and-strava-product-specification.md`
- The existing worker implementations under `integration_workers/` (`google`, `immich`, `strava`,
  `snipeit`)
- The shared package `core_shared/` (`telemetry`, `logging`, `metrics`, `stream_consumer`,
  `models/sync_job`, `database/`, `repositories/`)

Where earlier documents or implementations assume per-worker conventions, this specification should
be treated as the product-level refinement that unifies them.

## Product Goals

The worker standardisation effort should:

1. Provide **one well-trodden path** to add a new integration worker, so a developer (or AI agent)
   can scaffold a correct, tested, deployable worker by following a documented procedure rather than
   copying an existing worker.
2. Define **shared cross-worker concerns once** in `core_shared` — settings, OpenTelemetry, logging,
   ARQ configuration, and worker lifecycle — so they cannot drift apart again.
3. Ensure **fan-outs never block a worker slot**: an orchestrator that spawns batch jobs returns
   immediately and overall completion is tracked asynchronously.
4. Make worker **testing, CI, Docker, and uv setup consistent** across all workers, so the same
   commands and patterns apply everywhere.
5. Reinforce the architectural rule that **workers communicate with the backend only through events**
   — never writing journals or contacts directly, and never embedding SQL in `worker.py`.

## Product Principles

1. **Events are the only worker→backend channel.** Workers publish domain events to the outbox,
   which the relay forwards to the Redis Streams event bus. Workers never write to journals or
   contacts directly.
2. **`core_shared` owns cross-worker concerns.** Anything common to two or more workers — settings
   base, OTel setup, ARQ defaults, lifecycle, cron generation, test fixtures — lives in `core_shared`,
   not copied per worker.
3. **Repositories own all SQL.** `worker.py` contains orchestration and task definitions only. All
   database access goes through repositories (e.g. `SyncJobRepository`). No raw SQL in `worker.py`.
4. **Workers are isolated and independently testable.** Each worker is its own uv project with its own
   tests, Dockerfile, and CI matrix entry; it depends on `core_shared` as an editable source.
5. **Secrets are always `SecretStr`.** Every credential or secret-bearing setting uses Pydantic
   `SecretStr`, regardless of worker.
6. **Fan-outs are non-blocking by default.** Orchestrators hand off to children and return; a shared
   mechanism reconciles completion.

## Scope

### In Scope

- A shared base settings model in `core_shared` covering the fields every worker needs (including the
  OpenTelemetry block), with per-worker settings subclassing it.
- A shared ARQ worker configuration surface: standard defaults, Redis settings derivation, cron
  generation, and a shared `on_startup` / `on_shutdown` lifecycle factory.
- A non-blocking fan-out model: a new `IN_PROGRESS` sync-job status, parent↔child job tracking on
  `sync_jobs`, and a periodic reconciliation job that finalises in-progress parents.
- Standardisation of the stream-consumer registration pattern, shared test fixtures, and shared
  Python tooling configuration (`pyproject`/ruff/mypy/pytest), plus a canonical Dockerfile pattern.
- A `creating-a-new-worker` skill that documents the standardised procedure (specified here; authored
  as a dependent phase once the standardised surfaces exist).

### Out of Scope

- Changing the event-bus architecture itself (Redis Streams, outbox relay, consumer groups) — that is
  already defined and remains as-is.
- Building any new integration worker. This effort standardises the existing four and the procedure
  for future ones.
- Frontend changes. Sync-job status and progress are already surfaced; the new `IN_PROGRESS` status
  is additive and should display sensibly, but no UI redesign is required.
- Rewriting integration-specific business logic (API clients, transformers). Only the shared
  scaffolding around workers changes.

---

## Part 1: Shared Base Settings Model

### Problem Statement

Each worker declares its own settings class. Some are inline in `worker.py` (`google`, `strava`);
some are in a separate `*_settings.py` (`immich`, `snipeit`). The common fields — `database_url`,
`redis_url`, `log_level`, `worker_id`, `queue_name`, stream name, periodic-sync configuration, and the
entire OpenTelemetry block — are redeclared in every worker. `SecretStr` is used for secrets in
`google` but not in `immich`/`snipeit`. Redis URL handling diverges: `google` uses
`RedisSettings.from_dsn`, while `immich` hand-rolls a `_parse_redis_url` helper.

### Target Behaviour

`core_shared` defines a single `BaseWorkerSettings` (a Pydantic `BaseSettings`) that holds every field
common to workers:

| Field | Type | Notes |
|-------|------|-------|
| `database_url` | `SecretStr` | Required. |
| `redis_url` | `str` | Default `redis://redis:6379`. |
| `stream_name` | `str` | Default the shared domain-events stream name; no longer hardcoded per worker. |
| `worker_id` | `str` | Per-worker identifier. |
| `queue_name` | `str` | ARQ queue name. |
| `log_level` | `str` | Default `INFO`. |
| `enable_periodic_sync` | `bool` | Default `False`. |
| `sync_interval_hours` | `int` | Periodic sync cadence. |
| `enable_telemetry` | `bool` | Default `False`. |
| `otel_exporter_otlp_endpoint` | `str` | OTel block. |
| `otel_service_name` | `str` | OTel block. |
| `otel_resource_attributes` | `str` | OTel block. |

Each worker's settings class subclasses `BaseWorkerSettings` and adds **only** its
integration-specific fields (e.g. `google_client_id`, `immich_api_key`). All secret-bearing fields use
`SecretStr` in every worker.

A single shared helper derives ARQ `RedisSettings` from `redis_url` (standardising on
`RedisSettings.from_dsn`). The bespoke `immich` `_parse_redis_url` is retired.

The inline-vs-separate-file inconsistency is resolved: each worker keeps its settings in a dedicated
module that subclasses `BaseWorkerSettings`.

### Outcome

The OTel block and all common fields are defined once. Adding a worker means writing a small subclass
with the integration-specific secrets, not re-deriving the full settings surface.

---

## Part 2: Shared ARQ Worker Settings & Lifecycle

### Problem Statement

Every worker hand-writes its ARQ `WorkerSettings`: the `functions` list, `on_startup` / `on_shutdown`,
and operational defaults (`job_timeout`, `keep_result`, `max_tries`, `retry_delay`,
`health_check_interval`). These values diverge across workers (e.g. `job_timeout` 300s vs 600s) with
no shared rationale. The `startup` / `shutdown` hooks are near-identical across workers — build a
session factory from `database_url`, store it in `ctx`, launch the stream-consumer task, then cancel
it on shutdown — yet each worker reimplements them with minor variations (some close the session
factory, some check the consumer task state, some do neither). Cron-job generation is duplicated too
(`immich` has `_generate_cron_jobs`; `google` inlines the list).

### Target Behaviour

`core_shared` provides a shared way to assemble ARQ worker configuration:

- **Standard operational defaults** for `job_timeout`, `keep_result`, `max_tries`, retry/backoff, and
  `health_check_interval`, defined once and applied to all workers. A worker may override a default
  only with a documented reason.
- **Redis settings** derived through the shared helper from Part 1 (no per-worker parsing).
- **A shared cron-generation helper** that produces ARQ cron jobs from `enable_periodic_sync` and
  `sync_interval_hours`, replacing `immich._generate_cron_jobs` and `google`'s inline list.
- **A shared `on_startup` / `on_shutdown` factory.** The factory builds the database session factory,
  stores it (and settings) in the ARQ context, launches the worker's stream-consumer task, and on
  shutdown cancels the consumer task (handling `CancelledError`) and closes the session factory. A
  worker supplies only its functions list and its stream-consumer, not the lifecycle plumbing.

A per-worker ARQ `WorkerSettings` shrinks to its `functions` list, its consumer registration, and any
genuinely integration-specific overrides. Everything else comes from `core_shared`.

### Outcome

Worker lifecycle behaves identically everywhere (session handling, consumer launch/cancel, graceful
shutdown). Operational defaults are consistent and centrally tunable. A new worker declares its tasks
and consumer; the lifecycle is inherited.

---

## Part 3: Non-Blocking Fan-Outs

### Problem Statement

Orchestrator jobs spawn batch (child) jobs and then **block** on the result. For example, the Immich
orchestrators (`sync_immich_albums`, `sync_immich_people`) and the Strava activity sync enqueue child
batch jobs and await `asyncio.gather(*[job.result(timeout=290)])`. While blocked, the orchestrator
holds an ARQ worker slot for the entire fan-out, starving other jobs of concurrency, and the
hard-coded timeout (≈290s) is brittle for large syncs.

The data model cannot express this either. `SyncJobStatus`
(`core_shared/core_shared/models/sync_job.py`) has only `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`,
and `CANCELLED`. There is no status for "I have dispatched my children and am waiting on them", and no
parent↔child relationship: child jobs use synthetic IDs and are never persisted, so there is no record
of how many children exist or how many have finished.

### Target Behaviour

#### New status

`SyncJobStatus` gains an `IN_PROGRESS` value, used for a parent (orchestrator) job whose children have
been dispatched and are still running. The `ck_sync_jobs_status` check constraint is extended to allow
it. This is additive — existing statuses retain their meaning. (`RUNNING` continues to mean a job
actively executing on a worker; `IN_PROGRESS` specifically means "fan-out dispatched, awaiting
children".)

#### Parent↔child tracking

The `sync_jobs` table gains:

- `parent_job_id` — a self-referencing link from a child job to its orchestrator (null for top-level
  jobs).
- Child counters on the parent: `expected_children`, `completed_children`, `failed_children`.

Children are persisted as their own `sync_jobs` rows linked to the parent, replacing synthetic
non-persisted IDs.

#### Non-blocking orchestration

An orchestrator job now:

1. Determines the batches and **enqueues** the child jobs.
2. Persists each child as a `sync_jobs` row linked via `parent_job_id`, and sets the parent's
   `expected_children`.
3. Sets the parent status to `IN_PROGRESS` and **returns immediately** — no `asyncio.gather`, no held
   worker slot.

Each child, on completion, updates its own row and atomically increments the parent's
`completed_children` (or `failed_children`).

#### Completion via periodic reconciliation

A shared **reconciliation job** (defined in `core_shared`, run on a cron by each worker that uses
fan-outs) is the source of truth for parent completion. It periodically scans `IN_PROGRESS` parents
and:

- Transitions a parent to `COMPLETED` when all children have completed successfully.
- Transitions a parent to `FAILED` when children have failed (per the worker's failure policy), with
  the failure summary recorded on the parent.
- Handles **stuck/timed-out** fan-outs: a parent whose children have not progressed within a
  configured window is marked `FAILED` (or flagged for retry) rather than remaining `IN_PROGRESS`
  forever.

The child counters provide a fast path, but reconciliation against actual child rows is the
authoritative check, so a missed counter increment cannot strand a parent.

#### Migration

These schema changes (the new status value, `parent_job_id`, and the counter columns) require an
Alembic migration created per the `creating-migrations` skill. The blocking call sites — Immich
`sync_immich_albums` / `sync_immich_people` and the Strava activity fan-out — are migrated to the
non-blocking pattern.

### Outcome

Fan-outs release their worker slot immediately, so large syncs no longer starve other jobs. Parent
completion is observable (`IN_PROGRESS` → `COMPLETED`/`FAILED`) and resilient to lost counter updates
or stuck children.

---

## Part 4: Other Standardisation

### Stream-Consumer Registration

All workers run a Redis Streams consumer (subclassing `core_shared.stream_consumer.StreamConsumer`)
that filters domain events by type and routes them to handlers. Today each worker reimplements the
subclass and routing loop. The target is a shared registration convention where a worker **declares
its event routes** (event-type pattern → handler) and the shared consumer infrastructure runs the
loop, acknowledgement, and error handling. This removes per-worker boilerplate and makes the set of
events a worker consumes explicit and reviewable.

### Shared Test Fixtures

Each worker maintains its own `conftest.py` with overlapping fixtures (Redis mocks, session factory
mocks, ARQ context/harness, fake settings). The target is a shared fixture library under
`core_shared/testing/` that workers import, so the common fixtures exist once. Per-worker `conftest.py`
keeps only integration-specific fixtures. Tests remain deterministic and self-provisioning per the
project's test-first rules.

### Shared Python Tooling Configuration

Every worker's `pyproject.toml` repeats the same ruff, mypy, and pytest configuration and the same dev
dependency set, which drifts over time. The target is a shared base tooling configuration that workers
inherit, so linting/formatting/type-checking/test settings are consistent and changed in one place.
The `core_shared` editable source dependency and the Python version (`>=3.14`) are part of this
standard.

### Canonical Dockerfile

All workers already build `FROM pms-python-base`, install via uv, run a Redis-ping `HEALTHCHECK`, drop
to the `appuser` user, and `CMD ["python", "worker.py"]`. This pattern is documented as the canonical
worker Dockerfile so new workers copy a known-good template rather than an arbitrary existing worker.

### Outcome

The consumer loop, test fixtures, tooling config, and container build are defined once. Workers
declare intent (routes, integration fixtures, dependencies) rather than re-implementing scaffolding.

---

## Part 5: `creating-a-new-worker` Skill (Dependent Phase)

Once Parts 1–4 land, the standardised surfaces (base settings, ARQ factory/lifecycle, consumer
registration, shared fixtures, tooling config, Dockerfile template) become the building blocks for a
new worker. A skill should then document the end-to-end procedure so a new worker can be created
consistently.

This skill is **specified here but authored in a later phase**, because it must document the
standardised surfaces — writing it before they exist would document the old, divergent patterns.

The skill lives at `.claude/skills/creating-a-new-worker/SKILL.md`, following the established skill
format (YAML frontmatter with `name` and `description`, then numbered, actionable steps — see
`.claude/skills/creating-migrations/SKILL.md`). It must cover, as an ordered checklist:

- **(a) Tests first.** Following the project's test-first rule, the worker's `tests/unit/` and
  `tests/integration/` directories and their first tests are created before implementation, using the
  shared fixtures from `core_shared/testing/`.
- **(b) uv setup with `core_shared`.** Create the worker's uv project depending on `core_shared` as an
  editable source (`[tool.uv.sources] core_shared = { path = "../../core_shared", editable = true }`)
  and inheriting the shared tooling configuration.
- **(c) Docker image.** Add the canonical Dockerfile (`FROM pms-python-base`, uv install,
  Redis-ping `HEALTHCHECK`, `appuser`, `CMD ["python", "worker.py"]`).
- **(d) CI updates.** Add the worker to `.github/workflows/ci.yml` — a path-filter entry and a matrix
  entry so its unit and integration test jobs run — and to `.github/workflows/release.yml` — the build
  matrix component and its Dockerfile path mapping so its image is built and published on release.
- **(e) Worker setup.** Define the worker's settings as a subclass of `BaseWorkerSettings` and its ARQ
  `WorkerSettings` using the shared ARQ factory and `on_startup`/`on_shutdown` lifecycle, supplying
  only the functions list and stream-consumer registration.
- **(f) No SQL in `worker.py`.** All database access goes through repositories; `worker.py` holds
  orchestration and task definitions only.
- **(g) Communication via events only.** The worker talks to the backend exclusively through events
  (outbox → Redis Streams). It must never write to journals or contacts directly.

---

## Success Criteria

This work will be successful when:

1. `BaseWorkerSettings` (including the OTel block) exists in `core_shared` and all four workers
   subclass it; no common settings field or OTel field is redeclared per worker, and all secrets use
   `SecretStr`.
2. ARQ operational defaults, Redis settings derivation, cron generation, and `on_startup`/
   `on_shutdown` lifecycle are defined once in `core_shared` and consumed by all four workers; each
   worker's ARQ configuration is reduced to its functions list and consumer registration.
3. Fan-outs are non-blocking: orchestrators set `IN_PROGRESS` and return immediately, parent↔child
   relationships and counters are persisted in `sync_jobs`, and the periodic reconciliation job
   finalises parents (including stuck/timed-out cases). The Immich and Strava fan-outs no longer block
   on `asyncio.gather`.
4. The stream-consumer registration, test fixtures, Python tooling configuration, and Dockerfile
   pattern are shared; per-worker code declares intent rather than re-implementing scaffolding.
5. No worker's `worker.py` contains SQL, and every worker reaches the backend only through events.
6. A documented `creating-a-new-worker` skill exists (after Parts 1–4) that lets a developer or AI
   agent scaffold a complete, tested, deployable worker by following its steps, covering checklist
   items (a)–(g).

## Delivery Notes

This specification defines target product behaviour. Delivery should be phased to keep `main` green
and each worker functional throughout.

### Suggested Phasing

1. **Base settings.** Add `BaseWorkerSettings` (and the shared Redis-settings helper) to
   `core_shared`; migrate all four workers to subclass it; standardise `SecretStr`. No behaviour
   change.
2. **Shared ARQ factory & lifecycle.** Add the shared ARQ defaults, cron helper, and
   `on_startup`/`on_shutdown` factory to `core_shared`; migrate all four workers. No behaviour change.
3. **Non-blocking fan-outs.** Add the `IN_PROGRESS` status, `parent_job_id`, and child counters via an
   Alembic migration; implement the reconciliation job in `core_shared`; migrate the Immich and Strava
   fan-outs from blocking `asyncio.gather` to the non-blocking pattern. Verify end-to-end that large
   syncs complete and surface correct status.
4. **Shared consumer registration, fixtures, and tooling.** Introduce the consumer-route registration
   convention, `core_shared/testing/` fixtures, and the shared Python tooling configuration; migrate
   workers; document the canonical Dockerfile.
5. **Author the `creating-a-new-worker` skill.** With Parts 1–4 in place, write
   `.claude/skills/creating-a-new-worker/SKILL.md` covering checklist items (a)–(g).

Each phase should deliver working, tested functionality before the next begins. Phases 1 and 2 are
prerequisites for phase 5; phase 3 is independent of 1/2 but shares the same `core_shared` migration
discipline.
