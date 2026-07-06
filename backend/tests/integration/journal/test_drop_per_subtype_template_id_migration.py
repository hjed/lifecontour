"""Migration round-trip test for 0097 (drop per-subtype template_id columns).

Verifies the cleanup data-layer migration for ITER16-001 Phase 5:

- ``journal_canyoning_data`` / ``journal_climbing_data`` / ``journal_caving_data``
  each lose their now-unused ``template_id`` column (and its FK);
- the consolidated ``journal_abseiling_data.template_id`` is untouched by the drop;
- downgrade re-adds the three columns and re-backfills them from the consolidated
  ``abseiling_data.template_id`` (reversible, non-destructive round-trip);
- re-running the upgrade is idempotent.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_CANYONING_TEMPLATE = "11111111-1111-1111-1111-111111111111"
_CLIMBING_TEMPLATE = "22222222-2222-2222-2222-222222222222"
_CAVING_TEMPLATE = "33333333-3333-3333-3333-333333333333"

_SUBTYPE_TABLES = (
    "journal_canyoning_data",
    "journal_climbing_data",
    "journal_caving_data",
)


async def _insert_journal(conn: object, title: str) -> int:
    """Insert a minimal journal and return its generated id."""
    row = (
        await conn.execute(  # type: ignore[attr-defined]
            text(
                """
                INSERT INTO journals (
                    user_id, title, content,
                    event_date_range_start, event_date_range_end
                )
                VALUES ('test-user-123', :title, :content, now(), now())
                RETURNING id
                """
            ),
            {"title": title, "content": title},
        )
    ).fetchone()
    assert row is not None
    return int(row.id)


async def _insert_template(conn: object, template_id: str, template_type: str) -> None:
    await conn.execute(  # type: ignore[attr-defined]
        text(
            """
            INSERT INTO activity_templates (id, user_id, name, template_type)
            VALUES (:id, 'test-user-123', :name, :ttype)
            """
        ),
        {
            "id": template_id,
            "name": f"{template_type} template",
            "ttype": template_type,
        },
    )


async def _seed(engine_url: str) -> dict[str, int]:
    """Seed three abseiling-derived journals at the 0096 schema.

    Each has a subtype data row plus the matching ``journal_abseiling_data`` row
    carrying the consolidated ``template_id`` (the source of truth as of 0094).
    Returns the journal ids keyed by subtype.
    """
    engine = create_async_engine(engine_url)
    ids: dict[str, int] = {}
    try:
        async with engine.begin() as conn:
            await _insert_template(conn, _CANYONING_TEMPLATE, "canyoning")
            await _insert_template(conn, _CLIMBING_TEMPLATE, "climbing")
            await _insert_template(conn, _CAVING_TEMPLATE, "caving")

            ids["canyoning"] = await _insert_journal(conn, "Canyoning trip")
            ids["climbing"] = await _insert_journal(conn, "Climbing trip")
            ids["caving"] = await _insert_journal(conn, "Caving trip")

            await conn.execute(
                text("INSERT INTO journal_canyoning_data (journal_id) VALUES (:jid)"),
                {"jid": ids["canyoning"]},
            )
            await conn.execute(
                text("INSERT INTO journal_climbing_data (journal_id) VALUES (:jid)"),
                {"jid": ids["climbing"]},
            )
            await conn.execute(
                text("INSERT INTO journal_caving_data (journal_id) VALUES (:jid)"),
                {"jid": ids["caving"]},
            )
            # Every abseiling-derived journal already has an abseiling_data row
            # carrying the consolidated template reference (0094).
            template_by_subtype = {
                "canyoning": _CANYONING_TEMPLATE,
                "climbing": _CLIMBING_TEMPLATE,
                "caving": _CAVING_TEMPLATE,
            }
            for subtype, jid in ids.items():
                await conn.execute(
                    text(
                        "INSERT INTO journal_abseiling_data (journal_id, template_id) "
                        "VALUES (:jid, :tid)"
                    ),
                    {"jid": jid, "tid": template_by_subtype[subtype]},
                )
    finally:
        await engine.dispose()
    return ids


async def _abseiling_template_id(engine_url: str, journal_id: int) -> str | None:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            value = (
                await conn.execute(
                    text(
                        "SELECT template_id FROM journal_abseiling_data "
                        "WHERE journal_id = :jid"
                    ),
                    {"jid": journal_id},
                )
            ).scalar()
            return str(value) if value is not None else None
    finally:
        await engine.dispose()


async def _subtype_template_id(
    engine_url: str, table: str, journal_id: int
) -> str | None:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            value = (
                await conn.execute(
                    text(
                        f"SELECT template_id FROM {table} WHERE journal_id = :jid"  # noqa: S608
                    ),
                    {"jid": journal_id},
                )
            ).scalar()
            return str(value) if value is not None else None
    finally:
        await engine.dispose()


async def _column_exists(engine_url: str, table: str, column: str) -> bool:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            found = (
                await conn.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = :table AND column_name = :column
                        """
                    ),
                    {"table": table, "column": column},
                )
            ).scalar()
            return found is not None
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestDropPerSubtypeTemplateIdMigration:
    """0097 drop template_id from canyoning/climbing/caving subtype tables."""

    async def test_upgrade_drops_columns_and_downgrade_restores(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0096 the per-subtype columns still exist.
        run_alembic(url, "upgrade", "0096")
        for table in _SUBTYPE_TABLES:
            assert await _column_exists(url, table, "template_id")

        ids = await _seed(url)

        # 2. Upgrade drops the per-subtype columns; the consolidated one is kept.
        run_alembic(url, "upgrade", "0097")
        for table in _SUBTYPE_TABLES:
            assert not await _column_exists(url, table, "template_id")
        assert await _column_exists(url, "journal_abseiling_data", "template_id")
        assert (
            await _abseiling_template_id(url, ids["canyoning"]) == _CANYONING_TEMPLATE
        )
        assert await _abseiling_template_id(url, ids["climbing"]) == _CLIMBING_TEMPLATE
        assert await _abseiling_template_id(url, ids["caving"]) == _CAVING_TEMPLATE

        # 3. Downgrade re-adds the columns and re-backfills them from the
        #    consolidated abseiling_data.template_id (reversible round-trip).
        run_alembic(url, "downgrade", "0096")
        for table in _SUBTYPE_TABLES:
            assert await _column_exists(url, table, "template_id")
        assert (
            await _subtype_template_id(url, "journal_canyoning_data", ids["canyoning"])
            == _CANYONING_TEMPLATE
        )
        assert (
            await _subtype_template_id(url, "journal_climbing_data", ids["climbing"])
            == _CLIMBING_TEMPLATE
        )
        assert (
            await _subtype_template_id(url, "journal_caving_data", ids["caving"])
            == _CAVING_TEMPLATE
        )
        # Consolidated column still intact after the downgrade.
        assert await _abseiling_template_id(url, ids["caving"]) == _CAVING_TEMPLATE

        # 4. Re-applying the upgrade (a genuine second invocation of upgrade(),
        #    after the downgrade) drops the columns again and preserves the
        #    consolidated reference — the migration is re-runnable.
        run_alembic(url, "upgrade", "0097")
        for table in _SUBTYPE_TABLES:
            assert not await _column_exists(url, table, "template_id")
        assert await _abseiling_template_id(url, ids["caving"]) == _CAVING_TEMPLATE
