# Iteration 14: Worker Standardisation

**Status:** 🔵 PLANNED — sub-iterations and PR-sized phases defined; ready to implement
**Dependencies:** Iteration 5 (Redis Streams event bus, isolated worker pattern — COMPLETE). No external dependencies beyond what is already in `main`.
**Goal:** Consolidate the four integration workers (`google`, `immich`, `strava`, `snipeit`) onto a shared, standardised platform — shared settings, shared ARQ configuration and lifecycle, non-blocking fan-outs — and document the procedure for creating new workers.

## Overview

The four integration workers were built incrementally and have drifted: settings are partly duplicated and declared inconsistently (inline vs separate module, `SecretStr` only in some), ARQ configuration and lifecycle code is hand-written per worker with divergent values, and fan-out (batch) jobs block a worker slot for their whole duration. This iteration removes that duplication by moving shared concerns into `core_shared`, makes fan-outs non-blocking, and adds a skill documenting how to create a new worker.

This iteration realises the [Worker Standardisation Product Specification](../product-specifications/worker-standardisation-product-specification.md). It does **not** change the event-bus architecture established in iteration 5 — workers continue to communicate with the backend only via events (outbox → Redis Streams).

The work is split into six independently shippable **sub-iterations**, each broken into **PR-sized phases**. Phases are sized to merge to a green `main` independently within a **~600-line diff** (implementation + tests). A phase need not expose a user-facing change on its own — the sub-iteration is the shippable unit — but every phase must leave `main` green and introduce no broken or half-wired runtime path.

## Reference Documents

- **[Worker Standardisation Product Specification](../product-specifications/worker-standardisation-product-specification.md)** — approved product behaviour for this iteration
- **[Integration Architecture & Strava Product Specification](../product-specifications/integration-architecture-and-strava-product-specification.md)** — event-bus architecture this builds on
- **[Integration Architecture](../architecture/integration-architecture.md)** — event-driven integration patterns, worker structure
- **[Database Design](../architecture/database-design.md)** — transaction management, commit-as-you-go, schema standards
- **[Testing Strategy](../architecture/testing-strategy.md)** — worker unit tests, integration tests, conftest usage
- **[Code Quality Standards](../code-quality-standards.md)** — ruff/mypy/pytest configuration
- **[CI/CD Setup](../ci-cd-setup.md)** — worker test matrix and release image publishing
- **[Iteration 13: Contact Merge](./iteration-13-contact-merge.md)** — the PR-sizing reference this phase breakdown mirrors

### External Documentation

- **arq** — https://arq-docs.helpmanual.io/ (worker settings, cron, `RedisSettings.from_dsn`)
- **Pydantic Settings** — https://docs.pydantic.dev/latest/concepts/pydantic_settings/ (`BaseSettings`, `SecretStr`)
- **SQLAlchemy Core** — https://docs.sqlalchemy.org/en/20/ (use the `writing-sql` skill before authoring queries)
- **Alembic** — https://alembic.sqlalchemy.org/en/latest/ (use the `creating-migrations` skill for sequential naming)
- **OpenTelemetry Python** — https://opentelemetry.io/docs/languages/python/ (existing `core_shared/telemetry.py`)

## Delivery Rules

These rules apply to every phase below:

1. **Tests first:** write the failing tests for the slice before implementation (TDD red → green → refactor).
2. **Green main:** do not merge a phase unless relevant tests, linting (`ruff`), and type checks (`mypy`) pass for every affected worker and `core_shared`.
3. **PR size ≤ ~600 lines:** keep each phase within roughly a 600-line diff (implementation + tests); split further if it grows.
4. **Structural changes preserve behaviour:** ITER14-001, -002, -004, and -005 are refactors — observable worker behaviour must be identical before and after. Verify by running each affected worker's existing suite unchanged.
5. **Migrate-and-delete in the same phase:** when a phase moves a worker onto a shared surface, it must delete that worker's now-duplicate code in the same PR — no dead duplicate left behind.
6. **No SQL in `worker.py`:** all database access goes through repositories.
7. **Events only:** workers never write to journals or contacts directly.
8. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour. New shared code lands behind no runtime path until a migration phase wires it in.

## Dependency and Parallelisation Notes

- **ITER14-001 (Base Settings)** has no dependencies and lands first — the foundation other sub-iterations build on.
- **ITER14-002 (ARQ Settings & Lifecycle)** depends on **ITER14-001** (uses the settings base and shared Redis-settings helper).
- **ITER14-003 (Non-Blocking Fan-Outs)** is largely independent of 001/002 (it changes the `SyncJob` model and orchestrators); its reconciliation cron reuses the ITER14-002 cron helper if available, otherwise ships its own and is reconciled in 002.
- **ITER14-004 (Stream-Consumer Registration)** depends on **ITER14-002** (the shared lifecycle factory launches the consumer task).
- **ITER14-005 (Fixtures, Tooling & Dockerfile)** is independent and benefits from landing early so 001–004 reuse its fixtures.
- **ITER14-006 (Skill)** depends on **ITER14-001 through -005** and lands last.

| Sub-iteration | Depends on | Can parallelise with |
|---|---|---|
| ITER14-001 Base Settings | — | ITER14-003, ITER14-005 |
| ITER14-002 ARQ Settings & Lifecycle | ITER14-001 | ITER14-003, ITER14-005 |
| ITER14-003 Non-Blocking Fan-Outs | — (soft: ITER14-002 cron helper) | ITER14-001, ITER14-002, ITER14-005 |
| ITER14-004 Stream-Consumer Registration | ITER14-002 | ITER14-003, ITER14-005 |
| ITER14-005 Fixtures, Tooling & Dockerfile | — | all others |
| ITER14-006 Creating-a-Worker Skill | ITER14-001…005 | — |

## Sizing findings that shaped the phases

These were established by reviewing the current code and drive the phase boundaries below:

- **Settings are ~60% common but declared four different ways.** Common fields (`database_url`, `redis_url`, `worker_id`, `log_level`, `otel_*`) recur in all four; `google` declares them **inline** in `worker.py:54–99`, while `immich` (`immich_settings.py:13–34`), `strava` (`strava_settings.py:12–46`), and `snipeit` (`snipeit_settings.py:13–30`) use separate modules. `google`/`strava` use `SecretStr`; `immich`/`snipeit` use bare `str`. `snipeit` lacks `enable_periodic_sync`/`sync_interval_hours`. This split (SecretStr-already vs needs-conversion) shapes the 001 migration pairing.
- **Redis-URL parsing is duplicated.** `_parse_redis_url()` is copy-pasted in `immich/worker.py:788–798` and `snipeit/worker.py:402–412`; `google`/`strava` already use `RedisSettings.from_dsn(...)`. The shared helper lands in ITER14-001 and both copies are deleted in ITER14-002's migration.
- **Cron generation is duplicated three ways.** `immich` has a `_generate_cron_jobs()` helper (`worker.py:801–823`); `google` (`worker.py:3887–3909`) and `strava` (`worker.py:741–760`) inline equivalent logic; `snipeit` has none. One shared helper replaces all three.
- **Startup/shutdown are ~50 lines of near-identical code per worker.** `google:114–165`, `immich:56–91`, `strava:80–125`, `snipeit:42–77`. Differences are minor: `strava` adds an `add_done_callback` for error logging and checks `task.done()` before cancel; `google` closes the session factory. The shared factory must fold these variants in as options.
- **Fan-out handling is asymmetric and only partly persisted.** `immich.sync_immich_albums` (`worker.py:340–487`) **blocks** on `asyncio.gather(*[j.result(timeout=290)], return_exceptions=True)` (lines 454–459) and updates a `SyncJob`; `immich.sync_immich_people` (`worker.py:122–276`) enqueues children and returns but **does not persist** a `SyncJob`; `strava.sync_strava_activities` (`worker.py:426–532`) enqueues and returns, also without persisting. Children use deterministic synthetic IDs (e.g. `immich-album-batch-{job_id}-b{n}`) and are **never persisted** as `sync_jobs` rows. This drives 003's split: schema/repo first, then per-worker orchestrator migration.
- **`SyncJobRepository` has no hierarchy support.** Current public methods (`sync_job_repository.py`): `create`, `update_status`, `get_by_job_id`, `list_by_user`, `get_recent_failures`, `get_job_statistics`. There is **no** `parent_job_id`, no child query, and no atomic counter update — all net-new in ITER14-003 Phase 1.
- **Stream consumers all subclass `StreamConsumer`** (`core_shared/stream_consumer.py`, 312 lines) and override `__init__` (group/stream/patterns) + `_handle_event` routing. `google` has full routing (`stream_consumer_tasks.py:82–119`); `immich`/`strava`/`snipeit` are thin. A declarative route table replaces the per-worker `_handle_event` boilerplate.
- **Test fixtures and tooling are copy-pasted.** Per-worker `tests/integration/conftest.py` are ~114–121 lines and largely identical; each `pyproject.toml` (~134–147 lines) repeats the same ruff/mypy/pytest/dev config. Dockerfiles are already identical 22-line files `FROM pms-python-base` — they only need documenting as canonical.

---

## Task Breakdown

Each sub-iteration defines its objective, the specification it builds on, the outcomes its phases collectively satisfy, and a **phase breakdown**. Each phase lists a PR-size estimate, acceptance criteria, required test coverage, and required documentation updates. Sizes are estimates grounded in the line ranges above.

### ITER14-001: Shared Base Worker Settings

**Objective:** Introduce a single `BaseWorkerSettings` model in `core_shared` (including the OTel block) and migrate all four workers to subclass it, standardising `SecretStr` and Redis-settings derivation.

**Specification Reference:**
- [Part 1: Shared Base Settings Model](../product-specifications/worker-standardisation-product-specification.md#part-1-shared-base-settings-model)

**Dependencies:** None.

**Outcomes the phases must satisfy:**
- One `BaseWorkerSettings` defines every common field and the OTel block; workers add only integration-specific fields.
- All secret-bearing settings across all workers use `SecretStr`.
- A single shared helper derives ARQ `RedisSettings` from `redis_url`; the duplicated `_parse_redis_url` copies are gone.
- Worker boot behaviour is unchanged for the same env vars.

#### Phase 1: `BaseWorkerSettings` + shared Redis-settings helper (core_shared)
**PR Size:** ~250 lines (model ~90, helper ~30, tests ~130)
**Status:** ✅ DONE

Add the base model and helper to `core_shared`, fully unit-tested. Not yet consumed by any worker, so it merges green as additive code.

**Acceptance Criteria:**
- [x] `core_shared` exposes `BaseWorkerSettings` (Pydantic `BaseSettings`) with `database_url` (`SecretStr`), `redis_url`, `stream_name`, `worker_id`, `queue_name`, `log_level`, `enable_periodic_sync`, `sync_interval_hours`, and the OTel block (`enable_telemetry`, `otel_exporter_otlp_endpoint`, `otel_service_name`, `otel_resource_attributes`), with documented defaults.
- [x] A `redis_settings_from_url(redis_url)` helper returns ARQ `RedisSettings` via `RedisSettings.from_dsn`, handling host/port/db/password forms.
- [x] Both are exported from `core_shared/__init__.py`.

**Required Test Coverage:**
- **Unit:** field defaults and env-var loading; `SecretStr` masking of `database_url`; `redis_settings_from_url` parses representative `redis://` forms (with/without db index and password).

**Required Documentation Updates:**
- `docs/architecture/integration-architecture.md` — document `BaseWorkerSettings` as the canonical worker settings base and the standard field set.

**Progress notes (Phase 1 complete):**
- Implemented `BaseWorkerSettings` + `redis_settings_from_url` in new module `core_shared/core_shared/worker_settings.py`; both exported from `core_shared/__init__.py` and `__all__`.
- Per-worker fields (`worker_id`, `queue_name`, `otel_service_name`) take generic defaults so Phase 2 wiring causes no churn; `queue_name` defaults to `arq:queue` (arq's own default) so it is behaviourally inert for google/strava, which don't set it today.
- `model_config` standardised on `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")`.
- Added `pydantic-settings>=2.14.1` as a runtime dependency and `arq>=0.26` as a **dev-only** dependency of `core_shared` (refreshed `uv.lock`). `arq` is dev-only because it pins `redis<6` while `core_shared` requires `redis>=8` — reconciled by the existing `[tool.uv] override-dependencies` only when `core_shared` is the resolution root, but the shared `python-base` image installs it via a bare `uv pip install -e /core_shared` where the override does not apply. `redis_settings_from_url` therefore imports `arq` lazily so `import core_shared` works without `arq` (the backend never calls the helper; the workers that do always depend on `arq`).
- Tests: `core_shared/tests/test_worker_settings.py` (20 cases) — TDD red→green. Includes a legacy-equivalence guard parametrised over representative URLs that asserts the helper matches the old immich/snipeit `_parse_redis_url` output, so Phase 2 can delete those copies safely.
- **Test scope:** unit-only, per spec. Phase 1 is additive `core_shared` library code with no DB/API/UI/wired-worker surface, so there is no meaningful integration or e2e layer. Integration coverage (workers booting against real Redis/Postgres and resolving Redis+DB URLs) lands in **ITER14-001 Phase 2/3**; the e2e surface (`IN_PROGRESS` sync shown in the UI) lands in **ITER14-003 Phase 4**.
- Quality gates green in `core_shared/`: `ruff check`, `ruff format --check`, `mypy`, `pytest`.

#### Phase 2: Migrate `google` + `strava` settings onto the base
**PR Size:** ~300 lines (per-worker settings ~120, tests ~180)

**Status:** ✅ DONE

Migrate the two workers that already use `SecretStr`. `google`'s inline settings move into a dedicated settings module subclassing the base.

**Acceptance Criteria:**
- [x] `google` and `strava` settings classes subclass `BaseWorkerSettings`, declaring only integration-specific fields (`google_client_id`/`secret`, `encryption_key`, `max_concurrent_jobs`, `google_reserved_groups`, `webhook_base_url`; `strava_client_id`/`secret`, `encryption_key`). No common or OTel field is redeclared.
- [x] `google`'s settings move out of `worker.py` into a `google_settings.py` module (consistent with the others); `worker.py` imports it.
- [x] Both workers boot with their existing `.env` and produce identical effective configuration.

**Required Test Coverage:**
- [x] **Unit:** each worker's settings subclass loads integration-specific fields and inherits the base fields/defaults.
- [x] **Integration:** each worker boots with a representative `.env` and resolves Redis + DB URLs correctly (behaviour-preservation check).

**Required Documentation Updates:**
- [x] `google`/`strava` `README.md` settings sections updated to reference the base.

**Progress notes (Phase 2 complete — 2026-06-14, branch `emdash/iter14-001-2-migrate-google-strava`):**

- New `integration_workers/google/google_settings.py` exposes `GoogleSettings(BaseWorkerSettings)`; `google/worker.py` now imports it (`settings = GoogleSettings()`) and the inline `WorkerSettings`/`BaseSettings`/`SettingsConfigDict` block is deleted. The settings class is named `GoogleSettings` for consistency with `StravaSettings`; the ARQ worker class `GoogleWorkerSettings` is unchanged.
- `integration_workers/strava/strava_settings.py` re-bases `StravaSettings` onto `BaseWorkerSettings`, keeping only `strava_client_id`/`strava_client_secret`/`encryption_key` and the `worker_id`/`otel_service_name` identity overrides; the duplicated common/OTel fields and `model_config` block are removed.
- `encryption_key` is integration-specific (not in the base) and remains in both subclasses. `worker_id` and `otel_service_name` are overridden to preserve the exact prior values (`google-worker`/`strava-worker`); `queue_name`/`stream_name` stay at base defaults (workers still read the `*_ARQ_QUEUE_NAME` constants directly — wiring `settings.queue_name` in is ITER14-002).
- Both ARQ worker classes now derive Redis settings via the shared `redis_settings_from_url(settings.redis_url)` (replacing direct `RedisSettings.from_dsn(...)`), and the now-unused `from arq.connections import RedisSettings` import is dropped from each `worker.py`.
- Tests: `google/tests/unit/test_google_settings.py` (8) + `strava/tests/unit/test_strava_settings.py` (7) cover subclassing, integration-specific field loading, inherited base defaults, identity overrides, `SecretStr` masking, env-var loading, and required-field validation. `google`/`strava` `tests/integration/test_*_settings_integration.py` boot each worker from a representative `.env` and assert the ARQ class's `redis_settings` is derived via the shared helper (self-consistent, import-order-independent — no module reload, so the rest of the integration suite is unperturbed).
- Behaviour preservation verified: full `google` (309 unit / 50 integration) and `strava` (160 unit / 17 integration) suites pass unchanged; `core_shared` settings suite (20) green. Quality gates green: `ruff check`, `ruff format --check`, `mypy` for `core_shared`, `google`, `strava`.

#### Phase 3: Migrate `immich` + `snipeit` settings + `SecretStr` conversion
**PR Size:** ~300 lines (per-worker settings ~120, tests ~180)

Migrate the two workers that used bare `str`; convert secrets to `SecretStr` and add the periodic-sync fields `snipeit` lacked (inherited from the base, default disabled — no behaviour change).

**Acceptance Criteria:**
- [x] `immich` and `snipeit` settings classes subclass `BaseWorkerSettings`, declaring only integration-specific fields; common/OTel fields removed.
- [x] All secrets (`encryption_key`, `database_url`) use `SecretStr`; call sites read `.get_secret_value()` where the raw value is needed.
- [x] `snipeit` inherits `enable_periodic_sync`/`sync_interval_hours` (default disabled) — no scheduling behaviour change.

**Required Test Coverage:**
- [x] **Unit:** settings subclasses load correctly; `SecretStr` masking verified; secret call sites resolve the raw value.
- [x] **Integration:** both workers boot with a representative `.env` and resolve Redis + DB URLs correctly.

**Required Documentation Updates:**
- [x] `immich`/`snipeit` `README.md` settings sections updated.
- [x] `docs/code-quality-standards.md` — record the `SecretStr` requirement for all worker secrets.

**Progress notes (Phase 3 complete — 2026-06-14, branch `emdash/iter14-001-3-immich-and-snipeit-sync`):**

- `integration_workers/immich/immich_settings.py` and `integration_workers/snipeit/snipeit_settings.py` re-base `ImmichWorkerSettings`/`SnipeItWorkerSettings` onto `BaseWorkerSettings`, keeping only `encryption_key` (now `SecretStr`, default `SecretStr("")` to preserve the prior `str = ""` behaviour) plus the `worker_id`/`queue_name`/`otel_service_name` identity overrides. The duplicated common/OTel fields and the `model_config` block are removed; `from core_shared import BaseWorkerSettings` replaces `pydantic_settings.BaseSettings`.
- `database_url` is now the base's required `SecretStr`. Call sites read the raw value via `.get_secret_value()`: immich `worker.py` (`create_session_factory(...)` + 6× `ImmichAuthService(...)`) and snipeit `worker.py` (`create_session_factory(...)` + `Fernet(...encode())`). The `ImmichAuthService`/`SnipeItAuthService` constructors keep their `encryption_key: str` signature — only the callers unwrap.
- `snipeit` now inherits `enable_periodic_sync`/`sync_interval_hours` from the base (default-disabled), so it gains the fields without any scheduling-behaviour change. `redis_url`'s default consolidates from the workers' `redis://localhost:6379` to the base `redis://redis:6379` (deployments always set `REDIS_URL`). The per-worker `_parse_redis_url` helpers are left untouched — their replacement with `redis_settings_from_url` is ITER14-002.
- Tests: `immich/tests/unit/test_immich_settings.py` (9) + `snipeit/tests/unit/test_snipeit_settings.py` (10) cover subclassing, integration-specific field loading, inherited base defaults (incl. snipeit's newly-inherited periodic-sync fields), identity overrides, `SecretStr` masking, secret call sites resolving the raw value via `.get_secret_value()`, env-var loading, and required-field validation. `immich`/`snipeit` `tests/integration/test_*_settings_integration.py` (2 each) boot each worker from a representative `.env` (asserting `database_url.get_secret_value()` + Redis/DB resolution) and assert each ARQ class's `redis_settings` is self-consistent with the worker's own `_parse_redis_url`. The pre-existing `immich/tests/unit/test_periodic_sync.py` was updated to pass `SecretStr(...)` for `database_url`.
- Behaviour preservation verified: full `immich` (168 unit / 31 integration) and `snipeit` (162 unit / 14 integration) suites pass. Quality gates green: `ruff check`, `ruff format --check`, `mypy` for both workers.
- Docs: created `integration_workers/immich/README.md` and `integration_workers/snipeit/README.md` with Configuration/Environment-Variables sections (base-inherited + integration-specific tables), and added the `SecretStr` worker-secret rule to `docs/code-quality-standards.md`.

---

### ITER14-002: Shared ARQ Worker Settings & Lifecycle

**Objective:** Provide shared ARQ defaults, a shared cron helper, and a shared `on_startup`/`on_shutdown` lifecycle factory in `core_shared`; migrate all four workers so their ARQ `WorkerSettings` reduces to a functions list plus consumer registration.

**Specification Reference:**
- [Part 2: Shared ARQ Worker Settings & Lifecycle](../product-specifications/worker-standardisation-product-specification.md#part-2-shared-arq-worker-settings--lifecycle)

**Dependencies:** ITER14-001 (settings base + Redis-settings helper).

**Outcomes the phases must satisfy:**
- ARQ operational defaults, cron generation, and lifecycle are defined once and consumed by all four workers.
- Each worker's ARQ `WorkerSettings` is reduced to its functions list, consumer registration, and any documented override.
- The duplicated `_parse_redis_url`, `_generate_cron_jobs`/inline cron, and per-worker startup/shutdown are deleted.
- Startup/shutdown, cron scheduling, and retry behaviour are unchanged.

#### Phase 1: Shared ARQ toolkit — defaults, cron helper, lifecycle factory (core_shared)
**PR Size:** ~520 lines (defaults ~40, cron helper ~60, lifecycle factory ~130, tests ~290)
**Status:** ✅ DONE

Add the shared ARQ surface to `core_shared`, fully unit-tested. Not yet consumed, so it merges green.

**Acceptance Criteria:**
- [x] Shared ARQ defaults (`job_timeout`, `keep_result`, `max_tries`, retry/backoff, `health_check_interval`) defined once, with a documented way to override per worker.
- [x] A shared cron-generation helper produces ARQ cron jobs from `enable_periodic_sync` + `sync_interval_hours` (and an empty schedule when disabled), reproducing the existing `immich`/`google`/`strava` schedules.
- [x] A shared `on_startup`/`on_shutdown` factory builds the DB session factory, stores it and the settings in the ARQ `ctx`, launches a supplied stream-consumer coroutine as a task, and on shutdown cancels it (handling `CancelledError`) and closes the session factory. It folds in the existing variants as options: optional `add_done_callback` error logging (strava) and a `done()` check before cancel.

**Required Test Coverage:**
- [x] **Unit:** defaults application + override; cron helper schedules for representative intervals and the disabled case; lifecycle factory wires `ctx` keys, launches and cancels the consumer task, invokes the done-callback option, and closes the session factory on shutdown.

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — document the shared ARQ defaults, cron helper, and lifecycle factory as the standard worker bootstrap.

**Progress notes (Phase 1 complete — 2026-06-14, branch `emdash/iter14-001-1-shared-arq`):**

- New module `core_shared/core_shared/worker_arq.py` provides the three shared surfaces, all
  exported from `core_shared/__init__.py` (+ `__all__`): `SharedARQWorkerSettings` (defaults base) +
  `default_retry_delay` and the `DEFAULT_*` constants; `generate_cron_jobs`; `build_worker_lifecycle`
  (+ the `_log_consumer_task_done` callback ported from strava).
- **Defaults & override:** `SharedARQWorkerSettings` carries `job_timeout=300`, `keep_result=3600`,
  `max_tries=5`, `health_check_interval=30`, and `retry_delay=default_retry_delay` (google's
  exponential-backoff-with-jitter, capped at 900s, ported verbatim) as class attributes. A worker
  overrides a default by **redeclaring the attribute** (the documented mechanism); P2/P3 will use this
  for behaviour-preserving overrides (google `job_timeout=600`, strava `max_tries=20`). The base
  deliberately does **not** inherit arq's `WorkerSettingsBase` so importing it never imports `arq`.
- **Cron helper:** `generate_cron_jobs(func, *, enable_periodic_sync, sync_interval_hours, minute=0, unique=True)`
  reproduces the existing schedule (`hour = set(range(0, 24, max(1, interval)))`, top-of-hour,
  `unique=True`; `[]` when disabled). A parametrised equivalence guard asserts it matches the legacy
  `immich._generate_cron_jobs` output so P3 can delete that copy safely.
- **Lifecycle factory:** `build_worker_lifecycle(*, settings, consumer_factory, close_session_factory=False, log_consumer_errors=False)`
  returns `(on_startup, on_shutdown)`. `on_startup` builds the session factory from
  `settings.database_url.get_secret_value()`, stores `session_factory`/`settings`/`stream_consumer_task`
  in `ctx`, and launches `consumer_factory(session_factory, settings)`. `on_shutdown` does a
  `done()`-checked cancel (handling `CancelledError`, logging other exceptions) and optionally closes
  the session factory. The worker supplies `consumer_factory` as a closure wrapping its own
  `run_<worker>_stream_consumer(...)`, absorbing the per-worker arg differences (some pass `stream_name`).
- As with `redis_settings_from_url`, `arq` is imported lazily (only inside `generate_cron_jobs`); the
  arq-free `import core_shared` invariant is asserted in the verification step.
- Tests: `core_shared/tests/test_worker_arq.py` (30 cases) — TDD red→green: `TestSharedARQDefaults`,
  `TestDefaultRetryDelay`, `TestGenerateCronJobs` (incl. legacy-equivalence guard), and async
  `TestBuildWorkerLifecycle` (ctx wiring, launch, cancel, done-callback on/off, session-factory
  close on/off, missing/already-done task), plus the export check.
- **Test scope:** unit-only, per spec (Required Test Coverage above is **Unit**). Phase 1 is additive
  `core_shared` library code with no wired-worker/DB/API/UI surface, mirroring ITER14-001 P1.
  Integration coverage (each worker booting against real Redis/Postgres, running a trivial job, and
  shutting down cleanly) lands in **ITER14-002 Phase 2/3**; the e2e surface (`IN_PROGRESS` sync in the
  UI) lands in **ITER14-003 Phase 4**.
- Quality gates green in `core_shared/`: `ruff check`, `ruff format --check`, `mypy` (80 files),
  `pytest` (234 passed).

#### Phase 2: Migrate `google` + `strava` onto the shared ARQ toolkit
**PR Size:** ~360 lines (per-worker rewiring ~160, tests ~200)

**Status:** ✅ Complete (2026-06-15, branch `emdash/iter14-002-2-migrate-arq`).

**Acceptance Criteria:**
- [x] `google` and `strava` ARQ `WorkerSettings` use the shared defaults, cron helper, lifecycle factory, and `redis_settings_from_url`; each retains only its `functions` list, consumer registration, and documented overrides (`google` `max_concurrent_jobs`, `strava` `max_tries=20`).
- [x] Per-worker `startup`/`shutdown`, inline cron blocks, and any local Redis parsing are deleted.
- [x] Startup/shutdown, cron scheduling, and retry behaviour are unchanged.

**Required Test Coverage:**
- **Unit:** each worker's `WorkerSettings` exposes the expected functions/overrides; lifecycle delegates to the shared factory.
- **Integration:** each worker starts against real Redis + Postgres, runs a trivial job, and shuts down cleanly (consumer task cancelled, no leaked connections).

**Required Documentation Updates:**
- `google`/`strava` `README.md` updated to show the reduced `WorkerSettings`.

**Progress notes (Phase 2 complete — 2026-06-15, branch `emdash/iter14-002-2-migrate-arq`):**
- `google` and `strava` `WorkerSettings` now subclass `SharedARQWorkerSettings` (plus `arq.typing.WorkerSettingsBase` for `run_worker` typing) and use `build_worker_lifecycle`, `generate_cron_jobs`, and `redis_settings_from_url`. Deleted: each worker's `startup`/`shutdown`, the inline cron blocks, google's `retry_delay_func` (ported byte-for-byte to `core_shared.default_retry_delay`), and strava's `_on_consumer_task_done`.
- **Lifecycle options:** `google` → `close_session_factory=True` (disposes the engine; its old `hasattr(sf, "close")` cleanup was a no-op since `async_sessionmaker` has no `close`), `log_consumer_errors=False`. `strava` → `close_session_factory=False`, `log_consumer_errors=True` (real-time done-callback).
- **arq `get_kwargs` reads only the leaf `__dict__`** (inherited shared defaults are invisible to arq; it falls back to arq's own `Worker` defaults). The shared `job_timeout`/`keep_result`/`max_tries` equal arq's defaults, so inheritance is behaviourally transparent. The **one divergence is `health_check_interval`** (shared 30 vs arq 3600): google/strava never declared it and stay on arq's 3600 before and after — behaviour preserved. **Flag for Phase 3:** immich/snipeit currently declare `health_check_interval=30` on the leaf and must keep it declared (snipeit's documented override) — relying on inheritance would silently regress it to 3600. Unit tests assert via `arq.worker.get_kwargs(...)`, not class attributes, to make this visible.
- **`retry_delay` is not an arq `Worker` parameter** in our arq version (retry timing comes from `Retry(defer=...)`), so it was already an inert attribute; dropping it changes nothing.
- **strava `max_jobs=5`** is kept as an extra documented override (deviates from arq's default of 10); the AC text only names `max_tries=20`, but dropping `max_jobs` would change concurrency, violating "behaviour unchanged".
- **Tests:** strava `tests/unit/test_worker.py` (settings via `get_kwargs`, cron + lifecycle delegation; removed `TestOnConsumerTaskDone`); google new `tests/unit/test_worker_settings.py` and redirected `test_retry_strategy.py`/`test_retry_integration.py` to `core_shared.default_retry_delay`; new `tests/integration/test_worker_lifecycle_integration.py` in both workers (start → trivial DB job → clean shutdown against real Redis+Postgres). Local results: strava 166 unit + 19 integration; google 315 unit + 52 integration (1 pre-existing skip); ruff + mypy clean.

#### Phase 3: Migrate `immich` + `snipeit` onto the shared ARQ toolkit
**PR Size:** ~340 lines (per-worker rewiring ~150, tests ~190)

**Status:** ✅ Complete (2026-06-16, branch `emdash/iter14-002-3-migrate-arq`).

**Acceptance Criteria:**
- [x] `immich` and `snipeit` ARQ `WorkerSettings` use the shared defaults, cron helper (immich), lifecycle factory, and `redis_settings_from_url`; each retains only its `functions` list, consumer registration, and documented overrides (`health_check_interval=30` on both leaves — see note).
- [x] The duplicated `_parse_redis_url` (both workers), `immich._generate_cron_jobs`, and per-worker `startup`/`shutdown` are deleted.
- [x] Behaviour unchanged; `snipeit` (no cron) continues to schedule nothing.

**Required Test Coverage:**
- **Unit:** `WorkerSettings` functions/overrides; lifecycle delegates to the shared factory; no residual local Redis/cron helpers referenced.
- **Integration:** both workers start, run a trivial job, and shut down cleanly against real Redis + Postgres.

**Required Documentation Updates:**
- `immich`/`snipeit` `README.md` updated to show the reduced `WorkerSettings`.
- `docs/architecture/testing-strategy.md` — note the lifecycle factory's role in worker tests.

**Progress notes (Phase 3 complete — 2026-06-16, branch `emdash/iter14-002-3-migrate-arq`):**
- `immich` and `snipeit` ARQ `WorkerSettings` now subclass `SharedARQWorkerSettings` (plus `arq.typing.WorkerSettingsBase`) and use `build_worker_lifecycle`, `redis_settings_from_url`, and — for `immich` only — `generate_cron_jobs`. Each worker added a `_run_stream_consumer` adapter that feeds `redis_url`/`stream_name` from settings into its existing `run_*_stream_consumer`. Deleted from both: `_parse_redis_url`, the per-worker `startup`/`shutdown`; deleted from `immich`: `_generate_cron_jobs`.
- **Lifecycle options (both):** `close_session_factory=False`, `log_consumer_errors=True` — these reproduce the pre-migration startup/shutdown exactly (neither worker disposed the session factory; both logged consumer errors in the shutdown except-branch). Matches `strava`.
- **`health_check_interval=30` is redeclared on *both* leaves.** As flagged in the Phase 2 notes, arq's `get_kwargs` reads only the leaf `__dict__`, so the inherited shared `30` is invisible and arq would fall back to `3600`. Both workers declared `30` pre-migration, so "behaviour unchanged" requires keeping it declared (unlike google/strava, which never declared it and stay on arq's `3600`). The AC parenthetical named only `snipeit`; `immich` keeps it for the same behaviour-preservation reason.
- **`snipeit` has no periodic-sync task**, so it declares no `cron_jobs` and schedules nothing (unit test asserts `cron_jobs` is absent from the leaf and arq resolves none). `immich`'s cron schedule is produced by the shared helper; the existing `test_periodic_sync.py` cron-parity cases were redirected from the deleted `_generate_cron_jobs` to `core_shared.generate_cron_jobs` driven by the worker's periodic task, so the {0,6,12,18}/etc. hours are pinned unchanged.
- **Settings tests** that referenced `worker._parse_redis_url` were repointed to `core_shared.redis_settings_from_url`.
- **E2E:** not applicable — this is backend worker-infrastructure with no API/UI surface; the spec's Part 2 required coverage is unit + integration only.
- **Tests / gates (local):** immich 166 unit + 33 integration; snipeit 169 unit + 16 integration; core_shared `test_worker_arq.py` 32 unit; ruff check + ruff format --check + mypy clean for both workers.

---

### ITER14-003: Non-Blocking Fan-Outs

**Objective:** Make orchestrator (fan-out) jobs non-blocking: add an `IN_PROGRESS` sync-job status and parent↔child tracking to `sync_jobs`, change orchestrators to dispatch-and-return, and add a periodic reconciliation job that finalises in-progress parents.

**Specification Reference:**
- [Part 3: Non-Blocking Fan-Outs](../product-specifications/worker-standardisation-product-specification.md#part-3-non-blocking-fan-outs)

**Dependencies:** None hard. Soft: reuse the ITER14-002 cron helper for the reconciliation schedule.

**Outcomes the phases must satisfy:**
- `SyncJobStatus` gains `IN_PROGRESS`; `sync_jobs` gains `parent_job_id` and child counters; children persist as linked rows.
- Orchestrators dispatch children, mark the parent `IN_PROGRESS`, and return immediately — no blocking `asyncio.gather`.
- A shared reconciliation job finalises parents against child rows (authoritative), including stuck/timeout handling.
- The Immich and Strava fan-outs no longer hold a worker slot for their children's duration; final status remains correct.

#### Phase 1: Schema, model, migration & repository hierarchy support
**PR Size:** ~520 lines (model ~40, migration ~70, repository ~150, tests ~260)

**Status:** ✅ DONE

Net-new data layer, additive and not yet driven by orchestrators, so it merges green under test.

**Acceptance Criteria:**
- [x] `SyncJobStatus` gains `IN_PROGRESS`; the `ck_sync_jobs_status` check constraint is extended (existing statuses unchanged).
- [x] `sync_jobs` gains `parent_job_id` (self-referencing FK, nullable) and `expected_children`, `completed_children`, `failed_children` (default 0).
- [x] An Alembic migration adds the status value, columns, and constraint change, created per the `creating-migrations` skill (sequential numbering); it applies and rolls back cleanly.
- [x] `SyncJobRepository` gains methods to: create a child linked to a parent, set a parent's `expected_children`, atomically increment `completed_children`/`failed_children`, and list/aggregate children by parent.

**Required Test Coverage:**
- [x] **Unit:** status enum + constraint include `IN_PROGRESS`; repository counter increments are correct.
- [x] **Integration:** create parent + children, increment counters atomically under concurrency, query children by parent; migration up/down verified with `async_connection`/`clean_database`.

**Required Documentation Updates:**
- [x] `docs/architecture/database-design.md` — document the new `sync_jobs` columns and the `IN_PROGRESS` status value.

**Progress notes (Phase 1 complete — 2026-06-16, branch `emdash/iter14-003-fanout-schema`):**

- `core_shared/core_shared/models/sync_job.py`: `SyncJobStatus` gains `IN_PROGRESS = "in_progress"` (inserted after `RUNNING`; all other members unchanged). `SyncJob` gains `parent_job_id` (self-`ForeignKey("sync_jobs.job_id", ondelete="CASCADE")`, nullable, indexed) and `expected_children`/`completed_children`/`failed_children` (`Integer`, NOT NULL, `server_default="0"`). `ck_sync_jobs_status` extended to include `in_progress`.
- **`parent_job_id` references `job_id`, not the int PK** — orchestrators already hold their own ARQ `job_id` from the context and children carry the parent's `job_id`, so linking needs no extra `id` lookup, and the column name matches the natural key (`job_id` is unique, so it is a valid FK target).
- Migration `backend/app/migrations/versions/0088_add_sync_job_fanout_hierarchy.py` (revises `0087`): adds the four columns + `ix_sync_jobs_parent_job_id` index + `fk_sync_jobs_parent_job_id` self-FK, then swaps `ck_sync_jobs_status`. `downgrade` demotes any `in_progress` rows to `failed` before tightening the constraint, then drops the FK/index/columns. Round-trip (upgrade→head, downgrade→0087) verified green against a throwaway DB.
- `SyncJobRepository`: `create()` gains an optional `parent_job_id` (default `None`, backward-compatible). New methods `set_expected_children`, `increment_completed_children`/`increment_failed_children` (single-statement atomic `SET col = col + 1` via a whitelisted private `_increment_child_counter`), `list_children`, and `aggregate_children` (status counts via `COUNT(*) FILTER`, authoritative over the counters). All `SELECT`/`RETURNING` clauses and `_row_to_sync_job` were refactored onto a shared `_SYNC_JOB_COLUMNS` constant so the four new columns surface everywhere.
- **Tests:** unit `core_shared/tests/test_models.py` (enum + hierarchy columns) and `core_shared/tests/unit/repositories/test_sync_job_repository.py` (create-with-parent, set_expected_children, atomic increments, list/aggregate, row mapping); integration `backend/tests/integration/integrations/test_sync_job_hierarchy_repository.py` (parent+children, list/aggregate by parent, sequential accumulation, **true concurrent increments across independent connections** — no lost updates) and `test_sync_job_fanout_migration.py` (up/down round-trip; `in_progress` accepted after upgrade and rejected after downgrade; existing rows preserved). TDD red→green confirmed.
- **Test scope:** unit + integration only, per the spec's Required Test Coverage for this phase. Phase 1 is additive data-layer code with **no API/UI path**, so there is no meaningful e2e surface here; the e2e check (`IN_PROGRESS` shown in the UI without blocking other syncs) is owned by **ITER14-003 Phase 4** (see its Required Test Coverage). The concurrency integration test deliberately steps outside the savepoint fixture (independent committed connections + `finally` cleanup) because a single asyncpg connection serializes statements and cannot exercise concurrent `UPDATE`s.
- Quality gates green: `core_shared` `ruff format --check`/`ruff check`/`mypy`/`pytest` (250); `backend` `ruff check`/`mypy`; new integration tests (8) + the full `tests/integration/integrations/` suite + sync-job-touching backend unit tests pass with no regressions.

#### Phase 2: Shared reconciliation job (core_shared)
**PR Size:** ~450 lines (reconciler ~170, cron wiring ~20, tests ~260)

**Status:** ✅ DONE

Add the shared reconciliation function operating on the Phase 1 schema. It is a safe no-op until orchestrators emit `IN_PROGRESS` parents (Phases 3–4), so it merges green.

**Acceptance Criteria:**
- [x] A shared `reconcile_in_progress_parents` function scans `IN_PROGRESS` parents and transitions them to `COMPLETED` (all children completed) or `FAILED` (per failure policy) based on the child rows — counters are a fast path, child rows are authoritative.
- [x] Stuck/timeout handling: a parent whose children have not progressed within a configured window is marked `FAILED` (or flagged for retry) rather than remaining `IN_PROGRESS`.
- [x] A helper registers the reconciler on a cron (reusing the ITER14-002 cron helper) so any worker using fan-outs can schedule it.

**Required Test Coverage:**
- [x] **Unit:** transition logic for all-success, partial-failure, all-failure, and stuck/timeout cases.
- [x] **Integration:** seed `IN_PROGRESS` parents with various child states and verify the reconciler finalises each correctly; verify the no-op case (no in-progress parents).

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — document the reconciliation job and the non-blocking fan-out lifecycle.

**Progress notes (Phase 2 complete — 2026-06-17, branch `emdash/iter14-004-2-reconcile`):**

- `core_shared/core_shared/sync_reconciliation.py` (new): `decide_parent_outcome(...)` is the pure, unit-tested transition rule — child rows (`aggregate_children`) are **authoritative**, the parent counters are only a fast path. A child is terminal when `completed`, `failed`, or `cancelled` (`terminal = completed + failed + cancelled`); `done = total >= expected_children and terminal >= total`; `done` + any `failed`/`cancelled` → `FAILED` (fail-if-any, matching the current immich gather policy) with a `"{failed} failed and {cancelled} cancelled of {total} …"` summary; `done` + all completed → `COMPLETED`; not `done` and `seconds_since_update > stale_after_seconds` → `FAILED` (stuck/timeout); otherwise leave `IN_PROGRESS`. `reconcile_parents(repo, *, now, stale_after_seconds)` drives the repository loop and returns a `{scanned, completed, failed, still_in_progress}` summary; `reconcile_in_progress_parents(ctx)` is the ARQ entry point (reads `ctx["session_factory"]`/`ctx["settings"]`, opens a session, reconciles, commits). Safe no-op when no parents are `IN_PROGRESS`.
- `SyncJobRepository.list_in_progress_parents()` (new): `WHERE status = 'in_progress' AND parent_job_id IS NULL ORDER BY created_at ASC` — the only new SQL, kept in the repo layer and reusing `_SYNC_JOB_COLUMNS`/`_row_to_sync_job`. Staleness is read from the parent's `updated_at`, which the Phase 1 counter increments already bump.
- `BaseWorkerSettings.reconciliation_stale_after_seconds: int = 1800` (30 min) configures the stuck-fan-out window; `generate_reconciliation_cron(func, *, every_minutes=5, unique=True)` in `worker_arq.py` registers the reconciler on a frequent cron (reuses the lazy-`arq.cron` convention of `generate_cron_jobs`). Both new public surfaces plus `reconcile_*` are exported from `core_shared/__init__.py`.
- **Tests:** unit `core_shared/tests/unit/test_sync_reconciliation.py` (decision matrix + `reconcile_parents` loop + ARQ wrapper commit), `test_worker_arq.py` (cron minute-set/flooring/unique), and `test_sync_job_repository.py` (list_in_progress_parents mapping + SQL filter); integration `backend/tests/integration/integrations/test_sync_job_reconciliation.py` (all-complete→COMPLETED, partial/all-fail→FAILED, running→stays IN_PROGRESS, backdated→stuck FAILED, no-op, list-filter) against real Postgres via `clean_database`. TDD red→green confirmed.
- **Test scope:** unit + integration only, per the spec's Phase 2 Required Test Coverage. No API/UI surface in this phase, so no e2e here — the `IN_PROGRESS`-in-UI e2e check is owned by ITER14-003 Phase 4.
- Quality gates green: `core_shared` `ruff format --check`/`ruff check`/`mypy` (104 files)/`pytest` (269); `backend` `ruff`/`mypy` on the new test + reconciliation (7) and hierarchy (10) integration suites pass with no regressions.

#### Phase 3: Migrate Immich fan-outs to non-blocking
**PR Size:** ~480 lines (orchestrator changes ~160, child counter updates ~70, tests ~250)

**Status:** ✅ DONE

Make the asymmetric Immich orchestrators consistent and non-blocking.

**Acceptance Criteria:**
- [x] `sync_immich_albums` no longer blocks on `asyncio.gather`; it persists children linked to the parent, sets `expected_children`, marks the parent `IN_PROGRESS`, and returns. The reconciler finalises it.
- [x] `sync_immich_people` persists a parent + linked children (previously unpersisted), marks the parent `IN_PROGRESS`, and returns.
- [x] `sync_immich_album_batch` / `sync_immich_people_batch` update their own child rows and atomically increment the parent counters on completion/failure.
- [x] The Immich worker schedules the reconciliation cron.

**Required Test Coverage:**
- [x] **Unit:** orchestrators return without awaiting children; batch jobs increment the correct parent counter.
- [x] **Integration:** an album/people fan-out dispatches children against real Redis/Postgres, returns immediately, children update counters, and the reconciler transitions the parent to the correct final status. Regression: a large fan-out completes and reports correct totals.

**Required Documentation Updates:**
- [x] `immich` `README.md` — describe the non-blocking sync flow and status semantics.

**Progress notes (Phase 3 complete — 2026-06-19, branch `iter14-003-3-immich`):**

- `integration_workers/immich/worker.py`: both orchestrators (`sync_immich_albums`, `sync_immich_people`) now **drain their batch generator, persist one linked child `sync_jobs` row per batch, set `expected_children`, mark the parent `IN_PROGRESS`, and return** — the `asyncio.gather(*[j.result(timeout=290)])` blocking blocks (and the `arq.jobs.Job` fallback wiring) are deleted. Child rows are persisted and **committed before dispatch** (persist-then-enqueue) so a fast child can never update a not-yet-existing row. A shared `_persist_fanout_children(...)` helper does the create-children + `set_expected_children` + parent-status transition for both, collapsing the previously-asymmetric orchestrators onto one path; a zero-batch fan-out is marked `COMPLETED` directly (nothing to reconcile).
- Both batch jobs gained an optional `parent_job_id` param (orchestrator passes the parent's `job_id` positionally at enqueue; default `None` keeps direct/legacy invocation working). On success a batch marks **its own** row `COMPLETED` + `increment_completed_children(parent)` inside the same committed unit of work as the sync; on a **final**-attempt failure (`_is_final_attempt` reads `job_try`/`max_tries`, falling back to `DEFAULT_MAX_TRIES`) it records `FAILED` + `increment_failed_children(parent)` via `_record_child_failure` (own committed UoW, since the batch tx is already rolled back). A non-final failure just re-raises so ARQ retries without bumping a counter — child rows stay the reconciler's authoritative source.
- `WorkerSettings`: `reconcile_in_progress_parents` added to `functions`; `cron_jobs` is now `[*generate_cron_jobs(...), *generate_reconciliation_cron(reconcile_in_progress_parents)]` so the reconciler runs every 5 min regardless of whether periodic sync is enabled. Stale window comes from the inherited `BaseWorkerSettings.reconciliation_stale_after_seconds` (30 min); the startup hook already populates `ctx["session_factory"]`/`ctx["settings"]` the reconciler reads.
- **Tests (TDD red→green):** unit `tests/unit/test_immich_albums_orchestrator.py` + `test_immich_people_orchestrator.py` (return-without-awaiting, child persistence + `expected_children` + `IN_PROGRESS`, zero-batch→`COMPLETED`, credential-missing→`FAILED`), `test_immich_batch_counters.py` (success→completed+increment, final-failure→failed+increment, non-final-failure→no counter, legacy-no-parent skips counters), and `test_worker.py` (reconciler in `functions`; reconciliation cron present with periodic on **and** off, targeting `reconcile_in_progress_parents`); integration `tests/integration/test_immich_fanout_integration.py` (album + people fan-out against real Postgres/Redis: returns `IN_PROGRESS`, children persisted + dispatched on the real queue, batches increment counters, reconciler → `COMPLETED`; a final-try child failure → reconciler `FAILED` with message; large 25-batch fan-out reports correct totals → `COMPLETED`). The integration suite backs every worker session with a `session_factory` bound to the rolled-back `async_connection` (savepoint mode) and stubs only the external Immich SaaS (auth/API/sync service) — DB, repository and Redis queue are real.
- **Test scope:** unit + integration only, per this phase's Required Test Coverage. No frontend surface here, so no e2e — the `IN_PROGRESS`-in-UI e2e check is owned by **ITER14-003 Phase 4** (Strava + UI).
- Quality gates green: immich `ruff format --check`/`ruff check`/`mypy` (worker + new tests); unit suite (190) and the full integration suite (44, incl. the 5 new fan-out tests) pass with no regressions.

#### Phase 4: Migrate Strava fan-out to non-blocking
**PR Size:** ~360 lines (orchestrator changes ~120, child counter updates ~60, tests ~180)

**Status:** ✅ DONE

**Acceptance Criteria:**
- [x] `sync_strava_activities` persists a parent + linked children, sets `expected_children`, marks the parent `IN_PROGRESS`, and returns (it already does not block, but now persists hierarchy and status).
- [x] `sync_strava_activity_batch` updates its child row and atomically increments the parent counters.
- [x] The Strava worker schedules the reconciliation cron.
- [x] Sync status surfaces sensibly wherever sync jobs are displayed (`IN_PROGRESS` renders as an active state; no UI regression).

**Required Test Coverage:**
- [x] **Unit:** orchestrator persists hierarchy and returns; batch increments counters.
- [x] **Integration:** a Strava activity fan-out dispatches children, returns immediately, and the reconciler finalises the parent correctly.
- [x] **E2E (where surfaced):** trigger a Strava import from the integration dashboard and verify it shows `IN_PROGRESS` then resolves without blocking other syncs.

**Required Documentation Updates:**
- [x] `strava` `README.md` — describe the non-blocking sync flow.
- [x] `docs/tasks/periodic-sync-implementation.md` — cross-reference the reconciliation cron.

**Progress notes (Phase 4 complete — 2026-06-22, branch `iter14-003-4-strava-fanout`):**

- `integration_workers/strava/worker.py`: `sync_strava_activities` now **drains the activity-page generator into memory, idempotently owns its parent `sync_jobs` row, persists one linked child row per page, sets `expected_children`, marks the parent `IN_PROGRESS` and returns** — children are committed *before* dispatch (persist-then-enqueue). Unlike Immich (whose enqueuer seeds the parent), Strava enqueues no parent row anywhere, so the orchestrator owns it via `_ensure_parent_row` (create-if-missing on its own `ctx["job_id"]`, then mark `running`); a zero-page fan-out is marked `COMPLETED` directly. The drained loop keeps the `StravaRateLimitError`→`Retry` deferral. Strava-local fan-out helpers (`_persist_fanout_children`, `_record_child_terminal`/`_record_child_completion`/`_record_child_failure`, `_is_final_attempt`, `_coerce_int`) mirror the Immich worker's (workers stay isolated; the truly-shared reconciler already lives in `core_shared`).
- `sync_strava_activity_batch` gained an optional `parent_job_id` (orchestrator passes the parent's `job_id` positionally at enqueue; default `None` keeps direct/legacy invocation working). On success it marks **its own** child row `COMPLETED` + `increment_completed_children(parent)` in its own committed unit of work (the Strava batch owns per-activity transactions internally, so there is no shared session to join); on a **final**-attempt failure it records `FAILED` + `increment_failed_children(parent)`; a non-final failure — including a rate-limit `Retry` — just propagates so ARQ retries without bumping a counter. Child rows stay the reconciler's authoritative source (a counter is only bumped when the child-row update matched).
- `StravaWorkerSettings`: `reconcile_in_progress_parents` added to `functions`; `cron_jobs` is now `[*generate_cron_jobs(...), *generate_reconciliation_cron(reconcile_in_progress_parents)]` so the reconciler runs every 5 min regardless of whether periodic sync is enabled.
- **Frontend (`IN_PROGRESS` surface):** added `'in_progress'` to the `SyncStatus` union (`frontend/src/types/integrations.ts`); `useSyncJobStatus` keeps polling `in_progress` like `running`/`queued` (`frontend/src/lib/api/integrations.ts`); `SyncHistory` renders all statuses with human-readable labels (`In Progress`/`Completed`/…) and maps `in_progress` to the active (non-destructive) badge variant (`frontend/src/components/integrations/SyncHistory.tsx`). No component refactor; additive only (Strava surfaced no sync jobs before, so no regression).
- **Tests (TDD red→green):** unit `tests/unit/test_strava_orchestrator.py` (returns `in_progress` without awaiting children; child persistence + `expected_children` + `IN_PROGRESS`; persist-before-dispatch ordering + parent-id passed positionally; parent-row created when missing; zero-batch→`COMPLETED`; missing-auth→error; rate-limit mid-drain→`Retry`), `tests/unit/test_strava_batch_counters.py` (success→completed+increment, final-failure→failed+increment, non-final-failure→no counter, rate-limit→`Retry` no counter, legacy-no-parent skips counters, missing-child-row skips increment, `_is_final_attempt` coercion table), and `tests/unit/test_worker.py` (reconciler in `functions`; reconciliation cron present with periodic on **and** off, targeting `reconcile_in_progress_parents`); integration `tests/integration/test_strava_fanout_integration.py` (real Postgres/Redis: returns `IN_PROGRESS`, children persisted + dispatched on the real Strava queue, batches increment counters, reconciler→`COMPLETED`; a final-try child failure→reconciler `FAILED` with message; 25-batch fan-out totals correct; zero batches→`COMPLETED`). Frontend `SyncHistory.test.tsx` (RTL: `in_progress`→active "In Progress" badge; existing statuses unchanged) and e2e `integrations-ui.spec.ts` (trigger Strava import → Sync History shows the active `In Progress` state, another integration's sync still triggers while Strava is `IN_PROGRESS`, then resolves to `Completed`). The integration suite backs every worker session with a `session_factory` bound to the rolled-back `async_connection` (savepoint mode) and stubs only the external Strava SaaS (auth resolution + sync service) — DB, repository and Redis queue are real.
- Quality gates green: strava `ruff format --check`/`ruff check`/`mypy` (worker + new tests); unit suite (190) and the full integration suite (23, incl. the 4 new fan-out tests) pass with no regressions; frontend `pnpm quality:check` (format + lint + type-check) clean, `SyncHistory` RTL test passes, and the Strava e2e block (4 tests incl. the new `IN_PROGRESS` flow) passes on Chromium.

#### Phase 5: Extract shared fan-out helpers to `core_shared`
**PR Size:** ~450 lines (shared module + tests ~250, two-worker migrate-and-delete ~200)

**Status:** ✅ DONE

Phases 3–4 migrated Immich and Strava onto the non-blocking fan-out pattern, but
the worker-agnostic helper logic (`persist_fanout_children`, `record_child_terminal`,
`is_final_attempt`, `coerce_int`) was copied byte-for-byte into both `immich/worker.py`
and `strava/worker.py` (flagged as duplication by SonarCloud, and contrary to the
delivery rule "no dead duplicate left behind"). This phase moves that logic into a
single `core_shared` module and migrates both workers onto it, deleting the copies.
It also propagates Phase 4's retry-idempotency + authoritative-`expected_children`
hardening (originally added only to Strava) to Immich via the shared implementation.

**Acceptance Criteria:**
- [x] `core_shared` exposes `persist_fanout_children`, `record_child_terminal`, `is_final_attempt`, `coerce_int` (worker-agnostic; `persist_fanout_children` parameterised by `integration_source`, idempotent across retries, sets `expected_children` to the authoritative persisted-child count).
- [x] `immich/worker.py` and `strava/worker.py` import these from `core_shared` and their local duplicates are deleted (the thin per-worker session wrappers and Strava's `_ensure_parent_row` remain, as they legitimately differ).
- [x] Behaviour is unchanged for both workers; Immich gains the retry-idempotency/authoritative-count hardening for free.

**Required Test Coverage:**
- [x] **Unit:** `core_shared/tests/unit/test_fanout.py` covers the four helpers directly (coercion table, terminal row-match→increment vs unmatched→skip, persist creates N + idempotent skip-existing + authoritative `expected_children` + zero→`COMPLETED`). Both workers' existing unit + integration suites continue to pass against the shared implementation.

**Required Documentation Updates:**
- [x] `immich`/`strava` `README.md` — note the shared `core_shared` fan-out helpers.

**Progress notes (Phase 5 complete — 2026-06-22, branch `iter14-003-4-strava-fanout`):**

- `core_shared/core_shared/fanout.py` (new) hosts the worker-agnostic helpers — `coerce_int`, `is_final_attempt`, `record_child_terminal`, and `persist_fanout_children` (now parameterised by `integration_source`, idempotent skip-if-exists, authoritative `expected_children = max(drained, persisted)`). All four are exported from `core_shared/__init__.py` (+ `__all__`).
- `integration_workers/strava/worker.py` and `integration_workers/immich/worker.py` import the four via `from core_shared.fanout import … as _…` (private aliases preserve the existing call sites + tests) and **delete** their local copies; each orchestrator's `persist_fanout_children` call passes its `integration_source`. The per-worker session wrappers (`_record_child_completion`/`_record_child_failure`) and Strava's `_ensure_parent_row` remain local — they legitimately differ (Immich finalises a successful child inline in the sync session; Strava's batch owns its own per-activity transactions; only Strava must create its own parent row). Immich inherits Phase 4's retry-idempotency/authoritative-count hardening for free.
- **Tests:** `core_shared/tests/unit/test_fanout.py` (18) covers the helpers directly; the Immich orchestrator unit `_make_repo` gained a `list_children` mock (the shared persist queries it). No behavioural test changes were needed in either worker — the existing suites assert the same contract against the shared implementation.
- Quality gates green: `core_shared` `ruff format --check`/`ruff check`/`mypy`/`pytest` (304); `strava` `ruff`/`mypy` + 195 unit + 6 fan-out integration; `immich` `ruff`/`mypy` + 198 unit + 4 fan-out integration. Net diff is duplication-negative (−243/+412, the additions being the shared module + its tests + docs), clearing the SonarCloud new-code duplication finding from Phase 4.

---

### ITER14-004: Shared Stream-Consumer Registration

**Objective:** Replace each worker's hand-written `StreamConsumer` subclass and `_handle_event` routing with a shared registration convention where a worker declares its event routes and shared infrastructure runs the loop, acknowledgement, and error handling.

**Specification Reference:**
- [Part 4: Stream-Consumer Registration](../product-specifications/worker-standardisation-product-specification.md#stream-consumer-registration)

**Dependencies:** ITER14-002 (the shared lifecycle factory launches the consumer task).

**Outcomes the phases must satisfy:**
- A worker declares `event-type pattern → handler` routes; shared infrastructure runs `XREADGROUP`/ack/retry and dispatches, acking unmatched events immediately.
- Per-worker consumer boilerplate is deleted; the consumed-event set is reviewable from the route table.
- Failure isolation and at-least-once semantics are preserved.

#### Phase 1: Route-registration convention in `core_shared` ✅ COMPLETE
**PR Size:** ~350 lines (registry + dispatch ~150, tests ~200)

Extend `core_shared`'s `StreamConsumer` with a declarative route table + dispatch, fully unit-tested. Not yet consumed, so it merges green.

**Status:** Implemented. `EventRoute`/`EventHandler`, `event_type_matches`, and route-based dispatch added to `core_shared/core_shared/stream_consumer.py` (concrete `_handle_event` + `_match_route`; `routes` derive `event_type_patterns`); exported from `core_shared/__init__.py`. Legacy `_handle_event` override path preserved (existing backend + worker subclasses untouched, suites green).

**Acceptance Criteria:**
- [x] `core_shared` provides a way to declare routes (`event-type pattern → handler`); shared dispatch matches an event, invokes the handler, and acks; unmatched events are acked immediately.
- [x] Retry-on-failure via pending entries is preserved; the existing subclass override path remains supported (backward compatible) until workers migrate.

**Required Test Coverage:**
- [x] **Unit:** route matching (pattern → handler, unmatched → immediate ack), handler dispatch, retry-on-failure via pending entries. → `core_shared/tests/unit/test_stream_routing.py` (21 tests). Plus a real-Redis integration test of the generic routed consumer: `backend/tests/integration/infrastructure/events/test_routed_stream_consumer_integration.py` (3 tests).

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — document the route-registration convention as the standard way workers consume domain events. → "Stream-Consumer Route Registration" subsection added.

#### Phase 2: Migrate `google` + `immich` consumers to declarative routes
**PR Size:** ~300 lines (per-worker route tables ~120, tests ~180)

**Status:** ✅ Complete.

**Acceptance Criteria:**
- [x] `google` and `immich` declare route tables instead of subclassing/overriding `_handle_event`; the per-worker routing boilerplate is deleted. → both `GoogleWorkerStreamConsumer` and `ImmichWorkerStreamConsumer` now pass `routes=self._build_routes()` to `StreamConsumer` and no longer override `_handle_event`.
- [x] Each worker's consumed-event set is unchanged (regression-checked against the prior patterns). → route-table unit tests assert the exact consumed-event set (google: 3 journal + 2 tag + 4 contact; immich: 4 contact); existing routing tests retained as regression.

**Required Test Coverage:**
- [x] **Unit:** each worker's route table maps the expected event types to the right handlers; unmatched events acked. → `test_google_worker_route_table.py`, `test_stream_consumer_route_table.py` (immich).
- [x] **Integration:** a consumer reads real events from a Redis stream, dispatches matched events, acks unmatched, and retries a failing handler. → `test_google_worker_stream_consumer_integration.py` (extended with retry-on-failure) and new `test_immich_worker_stream_consumer_integration.py`.

**Required Documentation Updates:**
- [x] `google`/`immich` `README.md` consumer sections updated to the declarative pattern. → "Stream Consumer" subsection added to each README with the route table.

#### Phase 3: Migrate `strava` + `snipeit` consumers to declarative routes
**PR Size:** ~300 lines (per-worker route tables ~120, tests ~180)

**Status:** ✅ Complete.

**Acceptance Criteria:**
- [x] `strava` and `snipeit` declare route tables; per-worker routing boilerplate deleted. → both `StravaWorkerStreamConsumer` and `SnipeItWorkerStreamConsumer` now pass `routes=self._build_routes()` to `StreamConsumer` and no longer override `_handle_event`; the snipeit `snipeit.webhook_received` body was extracted into a dedicated `_handle_webhook_received` handler.
- [x] Consumed-event sets unchanged (`strava.*` prefix routing and the snipeit event set preserved). → route-table unit tests assert the exact consumed-event set (strava: single `strava.` prefix route; snipeit: `snipeit.webhook_received` + `GearItemUpdated` + `JournalCreated` + `JournalUpdated`); existing per-handler suites retained as regression.

**Required Test Coverage:**
- [x] **Unit:** route tables map the expected event types; prefix/pattern matching preserved. → `test_strava_worker_route_table.py` (prefix dispatch + exact set), `test_snipeit_worker_route_table.py` (per-handler mapping + exact set + unmatched ack); existing `test_stream_consumer.py` (strava) and `test_stream_consumer_tasks.py` (snipeit) retained.
- [x] **Integration:** each consumer reads, dispatches, acks unmatched, and retries a failing handler against real Redis. → new `test_strava_worker_stream_consumer_integration.py` (3 tests) and `test_snipeit_worker_route_consumer_integration.py` (3 tests); existing snipeit `test_stream_consumer_integration.py` (2 DB-backed handler tests) retained.

**Required Documentation Updates:**
- [x] `strava`/`snipeit` `README.md` consumer sections updated. → "Stream Consumer" subsection added to each README with the route table.

**Progress notes (Phase 3 complete — branch `iter14-004-3-strava-and-snipeit`):**

- `integration_workers/strava/stream_consumer_tasks.py` + `integration_workers/snipeit/stream_consumer_tasks.py` import `EventRoute` from `core_shared.stream_consumer`, declare `_build_routes()`, and delete their `_handle_event` overrides and `event_type_patterns`/`_STRAVA_EVENT_PATTERNS`/`_SNIPEIT_EVENT_TYPES` constants. Strava's single `strava.` prefix route preserves its wildcard semantics (placeholder handler still logs); snipeit's four exact routes preserve its consumed set, with the inline webhook routing moved verbatim into `_handle_webhook_received` and the per-event "processed event from stream" log preserved via a shared `_log_processed` helper called by each route handler.
- **Tests:** new route-table unit tests + real-Redis routed integration tests for both workers (dispatch matched / ack unmatched / retry-on-failure via pending entries), mirroring the google/immich Phase 2 pattern; existing handler suites kept as regression.
- Local quality gates run green: strava `ruff format`/`ruff check`/`mypy` + 200 unit + 3 consumer integration; snipeit `ruff`/`mypy` + 178 unit + 5 consumer integration. These are the worker lint/type/unit/integration checks enforced in CI; `core_shared` is untouched. (The real-Redis integration-test scaffolding is intentionally kept per-worker here — sharing it across workers is ITER14-005's `core_shared/testing/` scope.)

---

### ITER14-005: Shared Test Fixtures, Tooling Config & Canonical Dockerfile

**Objective:** Remove per-worker scaffolding duplication: shared test fixtures under `core_shared/testing/`, a shared Python tooling configuration workers inherit, and a documented canonical worker Dockerfile.

**Specification Reference:**
- [Part 4: Shared Test Fixtures](../product-specifications/worker-standardisation-product-specification.md#shared-test-fixtures)
- [Part 4: Shared Python Tooling Configuration](../product-specifications/worker-standardisation-product-specification.md#shared-python-tooling-configuration)
- [Part 4: Canonical Dockerfile](../product-specifications/worker-standardisation-product-specification.md#canonical-dockerfile)

**Dependencies:** None (benefits from landing early so 001–004 reuse the fixtures).

**Outcomes the phases must satisfy:**
- Shared worker fixtures exist once in `core_shared/testing/`; worker `conftest.py` keeps only integration-specific fixtures.
- Tooling config (ruff/mypy/pytest, dev deps, Python `>=3.14`) is defined once and inherited; quality checks behave identically.
- The canonical worker Dockerfile pattern is documented and all four workers conform.

#### Phase 1: `core_shared/testing/` shared fixtures
**PR Size:** ~300 lines (fixtures ~150, self-tests ~150)

Add shared fixtures, self-tested. Not yet adopted by workers, so it merges green.

**Acceptance Criteria:**
- [x] `core_shared/testing/` provides shared worker fixtures (Redis mock/client, session-factory mock, ARQ context/harness, fake `BaseWorkerSettings`), importable by worker test suites. → `core_shared/core_shared/testing/` (pytest plugin).
- [x] Fixtures are documented and behave as specified. → docstrings + `testing-strategy.md`; behaviour asserted by self-tests.

**Required Test Coverage:**
- [x] **Unit:** each fixture produces the expected object; a sample worker-style test runs purely on the shared fixtures. → `test_testing_fixtures.py` (12 tests) + `test_sample_worker_style.py` (1 test).

**Required Documentation Updates:**
- [x] `docs/architecture/testing-strategy.md` — document `core_shared/testing/` fixtures and how worker tests should consume them. → "Shared worker test fixtures — `core_shared.testing`" subsection added.

**Progress notes (Phase 1 complete — branch `iter14-005-1-shared-fixtures`):**

- Added shared worker unit-test fixtures under `core_shared/core_shared/testing/` (`__init__.py` declares the pytest-plugin surface; `fixtures.py` holds the implementations), consumed via `pytest_plugins = ["core_shared.testing"]`. Provides: `mock_redis` (AsyncMock Redis double with stream ops pre-seeded), `make_worker_settings`/`worker_settings` (real `BaseWorkerSettings` or subclass via `settings_cls`, `_env_file=None`, kwargs overrides), `session_factory_mock` (mock async session factory with awaitable `close` + `async with` session, matching `build_worker_lifecycle`'s contract), and `make_arq_ctx`/`arq_ctx` (ARQ `ctx` primed with `session_factory`/`settings`). The `make_*` helpers are also importable directly.
- **Additive only** — no worker adopts them yet (that is Phase 2), so `main` stays green.
- **Tests:** `core_shared/tests/unit/test_testing_fixtures.py` asserts each fixture/helper produces the expected object; `core_shared/tests/unit/test_sample_worker_style.py` is the spec-mandated worker-shaped test driving `build_worker_lifecycle` purely on the shared fixtures. Registered via a new top-level `core_shared/tests/conftest.py`.
- **Local quality gates green:** `ruff format --check` (112 files) + `ruff check` + `mypy core_shared` (83 files, no issues) + full `pytest` (333 passed, incl. 13 new). No worker/backend/frontend changes this phase. Used PEP 695 generics for `make_worker_settings` (`[SettingsT: BaseWorkerSettings]`) per ruff UP047.

#### Phase 2: Adopt shared fixtures across all workers
**PR Size:** ~350 lines (mostly deletions + imports across 4 conftests, ~90 net)

Migrate each worker's `tests/conftest.py` / `tests/integration/conftest.py` to import the shared fixtures and delete the duplicated common fixtures. Tests verify behaviour is unchanged.

**Acceptance Criteria:**
- [x] Each worker's `conftest.py` imports the shared fixtures and retains only integration-specific fixtures; duplicated common fixtures are deleted. → unit plugin via `pytest_plugins = ["core_shared.testing"]` in each top-level `tests/conftest.py`; DB fixtures imported from `core_shared.testing.integration` into each `tests/integration/conftest.py` (env preamble kept).
- [x] Every worker's existing test suite passes unchanged against the shared fixtures. → all unit + integration suites green at unchanged test counts (see progress notes).

**Required Test Coverage:**
- [x] **Integration:** each worker's full suite runs green against the shared fixtures (no new tests required beyond confirming green; add a thin smoke test per worker if a fixture seam needs it). → per-worker `tests/unit/test_shared_fixtures_wired.py` (unit seam) + `tests/integration/test_shared_db_fixtures.py` (DB seam); full suites green.

**Required Documentation Updates:**
- [x] Worker `README.md` testing sections updated to reference the shared fixtures. → all four worker `README.md`s + `google/tests/README.md` + `testing-strategy.md` updated.

**Progress notes (Phase 2 complete — branch `iter14-005-2-adopt-shared-fixtures`):**

- **DB integration fixtures extracted to `core_shared`.** The single biggest byte-identical cross-worker duplication was the DB scaffolding (`async_engine`, `async_connection`, `db_session`, autouse `apply_migrations`) plus the `get_workspace_env`/`get_async_database_url` helpers — repeated verbatim in all four `tests/integration/conftest.py`. Phase 1 only shared the unit mocks, so these were extracted here into a new `core_shared/core_shared/testing/integration.py` (with a robust `get_repo_root()` replacing the brittle `parent.parent…` chains). Pure helpers self-tested in `core_shared/tests/unit/test_testing_integration.py` (6 tests); DB fixtures validated by the worker integration suites.
- **Wiring decision — plugin vs import.** Unit fixtures are registered via `pytest_plugins = ["core_shared.testing"]` in each worker's **top-level** `tests/conftest.py` (created for immich/strava/snipeit; added to google's). The integration DB fixtures are **imported by name** into each `tests/integration/conftest.py` (re-exported via `__all__`), *not* via `pytest_plugins`. Reason: `pytest_plugins` is only honoured in the top-level conftest, and `apply_migrations` is `autouse=True, scope="session"` — a global plugin registration would force every unit-test run to `alembic upgrade head`. Importing keeps the autouse migration scoped to the integration subtree exactly as before. 12 test modules that imported `get_workspace_env`/`get_async_database_url` from `.conftest` were repointed at `core_shared.testing.integration`.
- **Aggressive unit-mock migration.** Each worker's dedicated `test_*_settings.py` `_make_settings` helper now delegates to `make_worker_settings(<WorkerSettings>, **kwargs)` (settings_cls passed **positionally** — the keyword form resolves to the bare `**overrides` overload and infers `BaseWorkerSettings`); inline ARQ `ctx`, redis-double, and lifecycle session-factory fixtures were migrated to `make_arq_ctx`/`make_mock_redis`/`make_session_factory_mock` where they matched the shared contract. Genuinely test-specific harnesses (strava's import-time-cron `_build_mock_settings`/`_import_worker`, session factories returning specific query rows, redis doubles with asserted `enqueue_job` returns) were deliberately left — aggressive ≠ breaking behaviour; no assertion or test was changed and per-worker test counts are unchanged.
- **Smoke tests added (8):** `test_shared_fixtures_wired.py` (4 unit) assert the shared unit fixtures resolve; `test_shared_db_fixtures.py` (4 integration) run `SELECT 1` via the shared `db_session`/`async_connection`.
- **Local quality gates green:** `core_shared` — ruff format/check, mypy (84 files), 340 pytest. Each worker — ruff format/check, mypy, and full suites: google 337 unit / 59 (+1 skip) integration; immich 208 / 46; strava 204 / 30; snipeit 182 / 21. Unit counts unchanged from baseline (only the 4 smoke tests added per the integration dir).

#### Phase 3: Shared tooling config + canonical Dockerfile
**PR Size:** ~300 lines (shared config ~120, per-worker pyproject trims ~120, docs ~60)

**Acceptance Criteria:**
- [ ] A shared base tooling configuration (ruff, mypy, pytest, dev dependency set, Python `>=3.14`) is defined once and inherited by all four workers; per-worker `pyproject.toml` no longer repeats it.
- [ ] `pnpm`/`uv` quality checks (`ruff`, `mypy`, `pytest`) behave identically across workers.
- [ ] The canonical worker Dockerfile pattern (`FROM pms-python-base`, uv install, Redis-ping `HEALTHCHECK`, `appuser`, `CMD ["python", "worker.py"]`) is documented and all four workers conform.

**Required Test Coverage:**
- **Integration:** each worker's suite and quality gates run green against the shared tooling config.

**Required Documentation Updates:**
- `docs/code-quality-standards.md` — document the shared tooling configuration and how workers inherit it.
- `docs/ci-cd-setup.md` — reference the canonical Dockerfile and shared tooling in the worker build/test description.
- `docs/architecture/integration-architecture.md` — link the canonical Dockerfile pattern.

---

### ITER14-006: `creating-a-new-worker` Skill

**Objective:** Author a skill documenting the end-to-end procedure for creating a new integration worker on the standardised platform.

**Specification Reference:**
- [Part 5: `creating-a-new-worker` Skill](../product-specifications/worker-standardisation-product-specification.md#part-5-creating-a-new-worker-skill-dependent-phase)

**Dependencies:** ITER14-001 through ITER14-005 (the skill documents the standardised surfaces).

**Outcomes the phases must satisfy:**
- A skill exists that lets a developer or AI agent scaffold a complete, tested, deployable worker by following its steps, covering checklist items (a)–(g).

#### Phase 1: Author and validate the `creating-a-new-worker` skill
**PR Size:** ~300 lines (skill doc; no production code)

Single phase — the skill is documentation, validated by following it to scaffold a throwaway sample worker.

**Acceptance Criteria:**
- [ ] `.claude/skills/creating-a-new-worker/SKILL.md` exists, following the established skill format (YAML frontmatter `name` + `description`, then numbered actionable steps — see `.claude/skills/creating-migrations/SKILL.md`).
- [ ] The skill covers, as an ordered checklist:
  - [ ] **(a)** Tests created first (`tests/unit/` + `tests/integration/`, using `core_shared/testing/` fixtures).
  - [ ] **(b)** uv project setup depending on `core_shared` as an editable source and inheriting the shared tooling config.
  - [ ] **(c)** Canonical Dockerfile (`FROM pms-python-base`, uv install, Redis-ping `HEALTHCHECK`, `appuser`, `CMD ["python", "worker.py"]`).
  - [ ] **(d)** CI updates — path-filter + matrix entry in `.github/workflows/ci.yml` (unit + integration jobs) and build component + Dockerfile mapping in `.github/workflows/release.yml`.
  - [ ] **(e)** Worker setup using `BaseWorkerSettings` and the shared ARQ factory/lifecycle (functions list + consumer routes only).
  - [ ] **(f)** No SQL in `worker.py` — all data access via repositories.
  - [ ] **(g)** Backend communication via events only (outbox → Redis Streams); never write journals or contacts directly.
- [ ] The skill references the canonical examples and the relevant `core_shared` surfaces by path.

**Required Test Coverage:**
- **Validation (manual):** follow the skill end-to-end to scaffold a throwaway sample worker and confirm each step is accurate (tests run, image builds, CI entries valid, worker boots). Fix any gaps found.

**Required Documentation Updates:**
- `docs/architecture/integration-architecture.md` — link the `creating-a-new-worker` skill as the canonical path for adding a worker.
- `CLAUDE.md` / skills index — ensure the new skill is discoverable per the project's skill registration convention.

---

## Delivery Notes

This iteration is sequenced so the foundational shared surfaces land first (ITER14-001, then -002), the independent fan-out work (ITER14-003) and scaffolding work (ITER14-005) proceed in parallel, the consumer convention (ITER14-004) follows the lifecycle factory, and the documentation skill (ITER14-006) lands last once everything it documents exists.

Every phase is sized to merge to a green `main` within ~600 lines and carries its own tests and documentation updates. Within each sub-iteration, the first phase adds shared `core_shared` code behind no runtime path; subsequent phases migrate workers onto it and delete the per-worker duplicates.

### Phase Summary

| Sub-iteration | Phases | Est. PRs |
|---|---|---|
| ITER14-001: Shared Base Settings | 3 | 3 |
| ITER14-002: Shared ARQ Settings & Lifecycle | 3 | 3 |
| ITER14-003: Non-Blocking Fan-Outs | 4 | 4 |
| ITER14-004: Stream-Consumer Registration | 3 | 3 |
| ITER14-005: Fixtures, Tooling & Dockerfile | 3 | 3 |
| ITER14-006: Creating-a-Worker Skill | 1 | 1 |
| **Total** | **17** | **17** |
