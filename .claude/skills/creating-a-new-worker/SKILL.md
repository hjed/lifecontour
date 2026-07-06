---
name: creating-a-new-worker
description: How to scaffold a new integration worker on the standardised core_shared platform. Use whenever adding a new ARQ integration worker so it inherits the shared settings, ARQ lifecycle, stream-consumer, fixtures, tooling config and Dockerfile instead of re-implementing them.
---

# Creating a New Integration Worker

Integration workers live under `integration_workers/<name>/` and run as ARQ worker
processes. Iteration 14 moved every piece of shared scaffolding into `core_shared`, so a
new worker declares only its intent (settings fields, task functions, event routes) and
inherits the rest. Work through the sections **top to bottom** — that order is the intended
workflow and enforces the project's test-first rule. The parenthesised letters `(a)`–`(g)`
are the spec's checklist labels (from the worker-standardisation product spec), so they are
**not** in alphabetical order here; follow the section order on the page, not the letters.

The **canonical reference worker** is `integration_workers/snipeit/` (the smallest). Open
it alongside these steps; every snippet below is copied from it or from `core_shared`. Use
paths verbatim; the relative `../../` paths assume you are inside `integration_workers/<name>/`.

Throughout, replace `<name>` with your worker's short name (e.g. `sample`) and `<Name>`
with its PascalCase form (e.g. `Sample`).

---

## (a) Write the tests first

Following the project's test-first rule, create the test directories and the first failing
tests **before** any implementation, using the shared fixtures from `core_shared/testing/`.

1. Create the layout:
   ```
   integration_workers/<name>/
     tests/
       conftest.py
       unit/
         test_worker.py
       integration/
         conftest.py
         test_<name>_integration.py
   ```

2. `tests/conftest.py` — register the shared **unit** fixtures. `pytest_plugins` is only
   honoured in the top-level conftest, so it lives here (copied from
   `integration_workers/snipeit/tests/conftest.py`):
   ```python
   """Top-level pytest configuration for the <name> worker test suite."""

   pytest_plugins = ["core_shared.testing"]
   ```
   This exposes `mock_redis`, `worker_settings`, `session_factory_mock` and `arq_ctx`
   (defined in `core_shared/core_shared/testing/fixtures.py`) as test arguments. The
   `make_*` factory variants (`make_worker_settings`, `make_mock_redis`, …) are importable
   from `core_shared.testing` when a test needs to build several instances.

3. `tests/unit/test_worker.py` — a first unit test asserting the worker's shape. It fails
   until step (e) creates `worker.py`:
   ```python
   from core_shared import BaseWorkerSettings

   from <name>_settings import <Name>WorkerSettings


   def test_settings_subclass_base() -> None:
       assert issubclass(<Name>WorkerSettings, BaseWorkerSettings)


   def test_worker_settings_has_functions() -> None:
       from worker import WorkerSettings

       assert WorkerSettings.functions  # non-empty task list
   ```

4. `tests/integration/conftest.py` — import the shared **integration** DB fixtures from
   `core_shared.testing.integration` (copied from
   `integration_workers/snipeit/tests/integration/conftest.py`). Import (do **not** use
   `pytest_plugins`) so the autouse `apply_migrations` stays scoped to this subtree:
   ```python
   """Pytest configuration for <name> worker integration tests."""

   import os

   from core_shared.testing.integration import (
       apply_migrations,
       async_connection,
       async_engine,
       db_session,
       get_async_database_url,
   )

   # Worker settings load from the environment at import time.
   if "DATABASE_URL" not in os.environ:
       os.environ["DATABASE_URL"] = get_async_database_url()

   __all__ = ["apply_migrations", "async_connection", "async_engine", "db_session"]
   ```
   `async_connection` is savepoint-wrapped and rolls back per test; `apply_migrations` is
   session-scoped and autouse. Add worker-specific fixtures (e.g. a mock HTTP transport for
   the external API) below the re-exports, as snipeit does.

5. Write one integration test that exercises a real DB round-trip (e.g. reading/writing a
   row your worker owns) using `async_connection` or `db_session`. It should fail until the
   corresponding data-access module exists.

To run these tests locally, follow the **`running-worker-integration-tests`** skill (it
brings up workspace-isolated Docker Postgres/Redis and sets the ports). Confirm the tests
**fail** now (red phase).

---

## (b) Create the uv project depending on `core_shared`

Create `integration_workers/<name>/pyproject.toml`, depending on `core_shared` as an
**editable path source** and inheriting the shared tooling config. Copy
`integration_workers/snipeit/pyproject.toml` and adjust the name/dependencies:

```toml
[project]
name = "<name>-worker"
version = "0.1.0"
description = "<Name> Integration Worker for Personal Management System"
license = {text = "AGPL-3.0"}
requires-python = ">=3.14"
dependencies = [
    "core_shared",
    "sqlalchemy[asyncio]>=2.0.51",
    "asyncpg==0.31.0",
    "httpx==0.28.1",
    "arq>=0.26",
    "structlog==26.1.0",
    "pydantic==2.13.4",
    "pydantic-settings==2.14.2",
    "redis[hiredis]>=8.0.1",
    # Add integration-specific deps here, e.g. "cryptography>=49.0.0" if the
    # worker decrypts stored credentials (snipeit does; a worker that doesn't
    # need it should omit it).
]

# core_shared is resolved from the sibling directory as an editable install.
[tool.uv.sources]
core_shared = { path = "../../core_shared", editable = true }

[dependency-groups]
dev = [
    "pytest==9.1.1",
    "pytest-asyncio==1.4.0",
    "ruff>=0.15.20",
    "mypy>=2.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["."]

# Inherit the shared ruff config (ruff's native inheritance).
[tool.ruff]
extend = "../../ruff.toml"
target-version = "py312"

# ruff per-file-ignores globs are anchored to THIS file's directory, so restate
# the test-dir ignores (the root ruff.toml patterns are anchored to the repo root).
[tool.ruff.lint.extend-per-file-ignores]
"tests/**/*" = ["B011", "DTZ"]
"tests/**/conftest.py" = ["E402"]
"tests/conftest.py" = ["E402"]

# arq pins redis<6 but core_shared needs redis>=8; reconcile at the worker root.
[tool.uv]
override-dependencies = ["redis>=8.0.0"]
```

The remaining tooling (`mypy.ini`, `pytest.ini`) is shared once at the repo root and
consumed via CLI flags — **not** duplicated per worker. See
`docs/code-quality-standards.md` for why. The canonical invocations are:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file ../../mypy.ini .
uv run pytest -c ../../pytest.ini --rootdir . tests/unit/
uv run pytest -c ../../pytest.ini --rootdir . tests/integration/
```

Run `uv sync` to confirm `core_shared` resolves as an editable dependency.

---

## (e) Define the settings and the worker

### Settings — subclass `BaseWorkerSettings`

Create `integration_workers/<name>/<name>_settings.py`. Subclass
`core_shared.BaseWorkerSettings` (defined in `core_shared/core_shared/worker_settings.py`)
and declare **only** integration-specific fields plus the per-worker identity overrides.
The common surface — `database_url`, `redis_url`, `stream_name`, logging, periodic-sync
cadence, reconciliation timeout and the full OpenTelemetry block — is inherited. Every
secret is a `pydantic.SecretStr`:

```python
from __future__ import annotations

from core_shared import BaseWorkerSettings
from pydantic import SecretStr


class <Name>WorkerSettings(BaseWorkerSettings):
    """Configuration for the <Name> integration worker."""

    # Integration-specific secrets — use SecretStr to keep them out of logs.
    <name>_api_key: SecretStr = SecretStr("")

    # Per-worker identity overrides (the rest come from BaseWorkerSettings).
    worker_id: str = "<name>-worker"
    queue_name: str = "arq:<name>"
    otel_service_name: str = "<name>-worker"
```

### `worker.py` — task functions + ARQ `WorkerSettings`

Create `integration_workers/<name>/worker.py`. It wires the shared ARQ toolkit
(`core_shared/core_shared/worker_arq.py`) and supplies only the functions list, the
consumer wiring, and the cron schedule. Structure (copied from
`integration_workers/snipeit/worker.py`):

```python
from __future__ import annotations

import sys
from typing import Any, cast

from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    generate_cron_jobs,
    redis_settings_from_url,
)
from core_shared.logging import configure_logging, get_logger
from core_shared.telemetry import setup_telemetry, trace_arq_job

from <name>_settings import <Name>WorkerSettings

settings = <Name>WorkerSettings()

configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)
logger = get_logger(__name__)


# --- Task functions (decorate with @trace_arq_job) ------------------------
@trace_arq_job
async def sync_<name>(ctx: dict, user_id: str) -> None:  # type: ignore[type-arg]
    """Orchestration only — data access lives in a repository/service module."""
    session_factory = ctx["session_factory"]
    ...


# --- Stream-consumer adapter for the shared lifecycle factory --------------
async def _run_stream_consumer(session_factory: Any, worker_settings: Any) -> None:
    """Bridge build_worker_lifecycle's (session_factory, settings) shape to the
    consumer's own keyword signature."""
    from stream_consumer_tasks import run_<name>_stream_consumer

    await run_<name>_stream_consumer(
        session_factory=session_factory,
        redis_url=worker_settings.redis_url,
        stream_name=worker_settings.stream_name,
    )


_on_startup, _on_shutdown = build_worker_lifecycle(
    settings=settings,
    consumer_factory=_run_stream_consumer,
    close_session_factory=False,   # True only if you must dispose the engine on shutdown
    log_consumer_errors=True,      # log consumer crashes in real time
)


class WorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    """ARQ settings: only functions, consumer wiring, cron and documented overrides.

    Operational defaults (job_timeout, keep_result, max_tries, retry backoff) are
    inherited from SharedARQWorkerSettings — redeclare one only with a documented reason.
    """

    functions: list[Any] = [sync_<name>]

    cron_jobs = generate_cron_jobs(
        sync_<name>,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )

    on_startup: StartupShutdown = cast("StartupShutdown", _on_startup)
    on_shutdown: StartupShutdown = cast("StartupShutdown", _on_shutdown)

    redis_settings = redis_settings_from_url(settings.redis_url)

    # Documented override: arq's get_kwargs reads only this leaf class's attributes,
    # so the inherited 30 is invisible and arq falls back to 3600. Redeclare to keep 30s.
    health_check_interval = 30


if __name__ == "__main__":
    from arq import run_worker

    setup_telemetry(settings)
    logger.info("Starting <Name> worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
```

### Stream consumer — subclass `StreamConsumer`

Create `integration_workers/<name>/stream_consumer_tasks.py`. Subclass
`core_shared.stream_consumer.StreamConsumer` and declare the event → handler routes in
`_build_routes()`. The shared base runs the read/ack/retry loop and dispatches matched
events; the route table is the single source of truth for the consumed-event set. A
top-level `run_<name>_stream_consumer(...)` builds the Redis client and runs the loop
(copied from `integration_workers/snipeit/stream_consumer_tasks.py`):

```python
import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent, create_stream_redis
from core_shared.stream_consumer import EventRoute, StreamConsumer

logger = structlog.get_logger()


class <Name>WorkerStreamConsumer(StreamConsumer):
    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "<name>-worker-1",
        batch_size: int = 10,   # events read per poll (tune for throughput)
        block_ms: int = 5000,   # how long each poll blocks waiting for events
    ) -> None:
        self._session_factory = session_factory
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="<name>-worker",
            consumer_name=consumer_name,
            batch_size=batch_size,
            block_ms=block_ms,
            routes=self._build_routes(),
        )

    def _build_routes(self) -> list[EventRoute]:
        """Declare the event-type → handler routes. Exact match, or prefix if the
        pattern ends with '.' (e.g. '<name>.' matches '<name>.webhook_received')."""
        return [
            EventRoute("GearItemUpdated", self._handle_gear_item_updated),
            EventRoute("<name>.webhook_received", self._handle_webhook_received),
        ]

    async def _handle_gear_item_updated(self, event: StreamEvent) -> None:
        ...

    async def _handle_webhook_received(self, event: StreamEvent) -> None:
        ...


async def run_<name>_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    redis_client = create_stream_redis(redis_url)
    stream_client = StreamClient(redis_client)
    consumer = <Name>WorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )
    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("<Name> worker stream consumer cancelled")
        raise
    finally:
        await redis_client.aclose()
```

---

## (f) Keep SQL out of `worker.py`

`worker.py` holds **orchestration and task definitions only**. Put database access in a
dedicated data-access/service module (see `integration_workers/snipeit/snipeit_sync_service.py`)
rather than embedding queries in the task functions. Task functions receive
`ctx["session_factory"]` and delegate the actual reads/writes to that module. This keeps
the entry point thin and the data access testable in isolation.

> **Note:** the reference `integration_workers/snipeit/worker.py` still has a few inline
> read-only `sqlalchemy.text(...)` auth/config lookups from before this convention. Treat
> them as legacy, **not** a pattern to copy — a new worker should route all data access
> through a data-access/service module.

---

## (g) Communicate with the backend via events only

The worker **never** writes to journals or contacts directly. It talks to the backend
exclusively through events:

- **Inbound** — it consumes domain events from the `pms:domain-events` Redis stream via the
  `StreamConsumer` routes above (the backend's outbox relay publishes them).
- **Outbound** — to push synced data back, it writes an **outbox event** row and lets the
  relay pick it up. Use the `OutboxEvent.create_*` factories in
  `core_shared/core_shared/models/outbox.py` (e.g. `create_journal_sync_event`,
  `create_contact_sync_event`) and add the row to the session inside a committing unit of
  work:
  ```python
  from core_shared.models.outbox import OutboxEvent

  async with session_factory() as session:
      event = OutboxEvent.create_journal_sync_event(
          journal_data=journal_data,
          integration_source="<name>",
          external_event_id=external_id,
          sync_action="created",
      )
      session.add(event)
      await session.commit()
  ```

Never `INSERT`/`UPDATE` journals or contacts from the worker — only outbox events.

---

## (c) Add the canonical Dockerfile

Create `integration_workers/<name>/Dockerfile`. It extends the shared `pms-python-base`
image (which provides Python 3.14, uv, `core_shared`, and the `appuser` account). Copy
`integration_workers/snipeit/Dockerfile`, changing only the two `snipeit` paths to `<name>`:

```dockerfile
# <Name> Integration Worker
# Extends the shared python-base image (Python 3.14, uv, core_shared, appuser).
FROM pms-python-base

# Copy worker pyproject.toml first for dependency caching.
COPY ./integration_workers/<name>/pyproject.toml .

# Copy worker source before install so the package is complete.
COPY ./integration_workers/<name>/ .
RUN uv pip install --system --no-cache-dir --no-sources .

# Health check — Python pings Redis using REDIS_URL from the environment.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis, os; r=redis.Redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

USER appuser

CMD ["python", "worker.py"]
```

---

## (d) Register the worker in CI and release

### `.github/workflows/ci.yml`

Add three entries so the worker's **unit and integration** jobs run (the jobs themselves
are matrix-driven and need no per-worker copy — only the registration below):

1. A `changes`-job output line (in the `outputs:` block):
   ```yaml
   worker_<name>: ${{ steps.filter.outputs.worker_<name> }}
   ```
2. A `dorny/paths-filter` entry (in the `filter` step's `filters:` block) — copy a
   `worker_snipeit:` block and swap the name; keep the shared-config paths:
   ```yaml
   worker_<name>:
     - 'integration_workers/<name>/**/*.py'
     - 'integration_workers/<name>/**/*.toml'
     - 'integration_workers/<name>/**/uv.lock'
     - 'integration_workers/<name>/**/Dockerfile*'
     - 'integration_workers/<name>/**/docker-compose*.yml'
     - 'integration_workers/<name>/**/docker-compose*.yaml'
     - 'ruff.toml'
     - 'mypy.ini'
     - 'pytest.ini'
   ```
3. A conditional block in the `Set matrix for workers` step (the `else` branch) so the
   worker joins the test matrix on a filtered PR:
   ```bash
   if [ "${{ steps.filter.outputs.worker_<name> }}" == "true" ]; then
     workers="$workers$comma\"<name>\""
     comma=","
   fi
   ```
   Also add `"<name>"` to the full push/`workflow_call`/`core_shared` list a few lines
   above:
   ```bash
   workers="[\"google\", \"immich\", \"snipeit\", \"strava\", \"<name>\"]"
   ```
   The `worker-unit-test` and `worker-integration-test` jobs already read
   `fromJSON(needs.changes.outputs.workers)`, so no further edits are needed.

### `.github/workflows/release.yml`

So the worker's image is built and published on release:

1. Add `<name>-worker` to the build matrix `component` list:
   ```yaml
   component: [backend, frontend, google-worker, strava-worker, snipeit-worker, immich-worker, <name>-worker]
   ```
2. Add a Dockerfile-path mapping `elif` in the `Set Dockerfile path` step:
   ```bash
   elif [ "${{ matrix.component }}" = "<name>-worker" ]; then
     echo "path=integration_workers/<name>/Dockerfile" >> $GITHUB_OUTPUT
   ```

---

## Finish: run the quality gates

From `integration_workers/<name>/`, with Docker services up (see the
**`running-worker-integration-tests`** skill), everything must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file ../../mypy.ini .
uv run pytest -c ../../pytest.ini --rootdir . tests/unit/ tests/integration/
```

The worker is complete when a developer following only these steps produces a worker whose
unit and integration tests pass, whose image builds from the canonical Dockerfile, whose CI
entries are valid, and which boots (`python worker.py`).
