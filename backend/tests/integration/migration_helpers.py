"""Schema-inspection helpers shared by migration round-trip tests.

Migration tests run against a ``throwaway_database`` rather than the shared
session connection, so they open their own short-lived engine per query. These
helpers wrap that pattern so each test only has to say what it expects the
schema to look like.
"""

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_VERSIONS = Path(__file__).resolve().parents[2] / "app" / "migrations" / "versions"


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
