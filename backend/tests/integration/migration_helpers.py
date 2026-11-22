"""Helpers shared by migration round-trip tests.

Migration tests run against a ``throwaway_database`` rather than the shared
session connection, so they open their own short-lived engine per query. These
helpers wrap that pattern so each test only has to say what it expects the
schema to look like.

``MigrationTemplates`` serves the first upgrade of a fresh throwaway database
from a template database already migrated to that revision, so each test does
not migrate an empty database from base. Every later command runs alembic.
"""

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_VERSIONS = _BACKEND_DIR / "app" / "migrations" / "versions"
_TEMPLATE_PID = re.compile(r"^tpl_(\d+)_")


class RunAlembic(Protocol):
    """The ``run_alembic`` fixture: ``alembic [-x k=v ...] <command> <target>``.

    Returns alembic's output (stdout then stderr, where its log lines go);
    raises ``RuntimeError`` carrying that output when the command fails.
    """

    def __call__(
        self,
        database_url: str,
        command: str,
        target: str,
        *,
        x_args: Mapping[str, str] | None = None,
    ) -> str: ...


def run_alembic_subprocess(
    database_url: str,
    command: str,
    target: str,
    *,
    x_args: Mapping[str, str] | None = None,
) -> str:
    """Run ``alembic [-x k=v ...] <command> <target>`` against ``database_url``.

    Returns alembic's output (stdout then stderr, where its log lines go);
    raises ``RuntimeError`` carrying that output when the command fails.
    """
    env = {**os.environ, "ENVIRONMENT": "test", "DATABASE_URL": database_url}
    x_flags = [
        flag
        for key, value in (x_args or {}).items()
        for flag in ("-x", f"{key}={value}")
    ]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *x_flags, command, target],
        cwd=str(_BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {command} {target} failed:\n{result.stdout}\n{result.stderr}"
        )
    return f"{result.stdout}\n{result.stderr}"


def _admin_engine(admin_url: URL) -> Engine:
    """A synchronous engine for ``CREATE``/``DROP DATABASE`` on the server."""
    return create_engine(
        admin_url.set(drivername="postgresql+psycopg2"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )


def _drop(engine: Engine, db_name: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


class MigrationTemplates:
    """Template databases migrated to a revision, cloned into fresh databases.

    A template is built the first time its revision is asked for: by cloning the
    nearest template already built for an ancestor revision (or an empty
    database) and running ``alembic upgrade`` on it, so every template is the
    product of real migrations. Cloning one costs a ``CREATE DATABASE ...
    TEMPLATE`` instead of migrating from base.

    Fresh databases are tracked by name, because tests pass rendered URL
    strings rather than the ``URL`` the fixture yielded.
    """

    def __init__(self, admin_url: URL, *, prefix: str) -> None:
        self._admin_url = admin_url
        self._prefix = prefix
        self._engine = _admin_engine(admin_url)
        # alembic.ini's ``script_location`` is relative to the working
        # directory, so pin it: pytest may be launched from the repository root.
        config = Config(str(_BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(_VERSIONS.parent))
        self._script = ScriptDirectory.from_config(config)
        self._sources: dict[str, str | None] = {}
        self._fresh: set[str] = set()
        self.clones = 0

    def register_fresh(self, db_name: str) -> None:
        """Mark ``db_name`` as just created: its first upgrade may be a clone."""
        self._fresh.add(db_name)

    def is_fresh(self, db_name: str) -> bool:
        return db_name in self._fresh

    def forget(self, db_name: str) -> None:
        """``db_name`` has been touched; from now on alembic runs for real."""
        self._fresh.discard(db_name)

    def template_name(self, revision: str) -> str:
        return f"{self._prefix}_{self._resolve(revision)}"

    def template_source(self, revision: str) -> str | None:
        """The template a built template was cloned from; ``None`` if from empty."""
        return self._sources[self._resolve(revision)]

    def clone_into(self, db_name: str, revision: str) -> None:
        """Replace ``db_name`` with a copy of the template at ``revision``."""
        template = self._ensure(self._resolve(revision))
        self._recreate(db_name, template)
        self.forget(db_name)
        self.clones += 1

    def drop_database(self, db_name: str) -> None:
        _drop(self._engine, db_name)

    def drop_all(self) -> None:
        """Drop every template this registry built."""
        for revision in list(self._sources):
            _drop(self._engine, f"{self._prefix}_{revision}")
        self._sources.clear()
        self._engine.dispose()

    def _resolve(self, revision: str) -> str:
        script = self._script.get_revision(revision)
        if script is None:
            raise ValueError(f"unknown revision {revision!r}")
        return script.revision

    def _ensure(self, revision: str) -> str:
        name = f"{self._prefix}_{revision}"
        if revision in self._sources:
            return name
        source = next(
            (
                f"{self._prefix}_{script.revision}"
                for script in self._script.iterate_revisions(revision, "base")
                if script.revision in self._sources
            ),
            None,
        )
        self._recreate(name, source)
        try:
            run_alembic_subprocess(
                self._admin_url.set(database=name).render_as_string(
                    hide_password=False
                ),
                "upgrade",
                revision,
            )
        except BaseException:
            _drop(self._engine, name)
            raise
        self._sources[revision] = source
        return name

    def _recreate(self, db_name: str, template: str | None) -> None:
        clause = f' TEMPLATE "{template}"' if template is not None else ""
        _drop(self._engine, db_name)
        with self._engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"{clause}'))


def drop_stale_templates(admin_url: URL) -> None:
    """Drop templates left by sessions whose process is gone (a crashed run)."""
    engine = _admin_engine(admin_url)
    try:
        with engine.connect() as conn:
            names = conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE 'tpl\\_%'")
            ).scalars()
            stale = [
                str(name)
                for name in names
                if (match := _TEMPLATE_PID.match(str(name))) is not None
                and not _process_is_alive(int(match.group(1)))
            ]
        for name in stale:
            _drop(engine, name)
    finally:
        engine.dispose()


def _process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def table_exists(engine_url: str, table: str) -> bool:
    """Return whether ``table`` exists in the database at ``engine_url``."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = :table
                        """
                    ),
                    {"table": table},
                )
            ).scalar()
            return found is not None
    finally:
        await engine.dispose()


async def columns(engine_url: str, table: str) -> set[str]:
    """Return the column names of ``table`` in the database at ``engine_url``."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = :table
                        """
                    ),
                    {"table": table},
                )
            ).fetchall()
            return {str(row.column_name) for row in rows}
    finally:
        await engine.dispose()


async def index_exists(engine_url: str, index: str) -> bool:
    """Return whether ``index`` exists in the database at ``engine_url``."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text("SELECT 1 FROM pg_indexes WHERE indexname = :index"),
                    {"index": index},
                )
            ).scalar()
            return found is not None
    finally:
        await engine.dispose()


async def tables_with_column(engine_url: str, column: str) -> set[str]:
    """Return the base tables in the database at ``engine_url`` that have ``column``."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT c.table_name
                        FROM information_schema.columns c
                        JOIN information_schema.tables t
                          USING (table_schema, table_name)
                        WHERE c.table_schema = 'public'
                          AND c.column_name = :column
                          AND t.table_type = 'BASE TABLE'
                        """
                    ),
                    {"column": column},
                )
            ).fetchall()
            return {str(row.table_name) for row in rows}
    finally:
        await engine.dispose()


def load_revision(filename: str) -> ModuleType:
    """Load a revision by its file name — revision files are not importable by
    module name, since they start with a digit."""
    spec = importlib.util.spec_from_file_location(
        f"migration_{filename.split('_', 1)[0]}", _VERSIONS / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def execute(
    engine_url: str, sql: str, params: Mapping[str, Any] | None = None
) -> Any:
    """Run ``sql`` in its own transaction; return its scalar when it returns rows."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), dict(params or {}))
            return result.scalar() if result.returns_rows else None
    finally:
        await engine.dispose()


async def link_owners(engine_url: str) -> dict[str, str | None]:
    """Each ``sync_metadata`` row's owner, keyed by its external id."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT external_id, user_id FROM sync_metadata")
                )
            ).fetchall()
            return {str(row.external_id): row.user_id for row in rows}
    finally:
        await engine.dispose()
