"""Schema-inspection helpers shared by migration round-trip tests.

Migration tests run against a ``throwaway_database`` rather than the shared
session connection, so they open their own short-lived engine per query. These
helpers wrap that pattern so each test only has to say what it expects the
schema to look like.
"""

from collections.abc import Mapping
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class RunAlembic(Protocol):
    """The ``run_alembic`` fixture: ``alembic [-x k=v ...] <command> <target>``.

    Raises ``RuntimeError`` carrying alembic's output when the command fails.
    """

    def __call__(
        self,
        database_url: str,
        command: str,
        target: str,
        *,
        x_args: Mapping[str, str] | None = None,
    ) -> None: ...


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
