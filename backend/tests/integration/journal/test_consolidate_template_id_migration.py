"""Migration round-trip test for 0094 (consolidate template_id onto abseiling_data).

Verifies the additive data-layer migration for ITER16-001 Phase 1:

- ``journal_abseiling_data`` gains a nullable ``template_id`` UUID FK;
- the value is backfilled from the existing per-subtype ``template_id`` columns
  on ``journal_canyoning_data`` / ``journal_climbing_data`` / ``journal_caving_data``
  (each maps to the journal's ``journal_abseiling_data`` row);
- the ``activity_templates`` type CHECK accepts the new ``'abseiling'`` type after
  upgrade and rejects it again after downgrade;
- downgrade is non-destructive for the old subtype columns (they retain values);
- re-running the upgrade is idempotent.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

_CANYONING_TEMPLATE = "11111111-1111-1111-1111-111111111111"
_CLIMBING_TEMPLATE = "22222222-2222-2222-2222-222222222222"
_CAVING_TEMPLATE = "33333333-3333-3333-3333-333333333333"


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
    """Seed three abseiling-derived journals at the 0093 schema.

    Each has a subtype data row carrying ``template_id`` plus the matching
    ``journal_abseiling_data`` row (which has no ``template_id`` column yet).
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
                text(
                    "INSERT INTO journal_canyoning_data (journal_id, template_id) "
                    "VALUES (:jid, :tid)"
                ),
                {"jid": ids["canyoning"], "tid": _CANYONING_TEMPLATE},
            )
            await conn.execute(
                text(
                    "INSERT INTO journal_climbing_data (journal_id, template_id) "
                    "VALUES (:jid, :tid)"
                ),
                {"jid": ids["climbing"], "tid": _CLIMBING_TEMPLATE},
            )
            await conn.execute(
                text(
                    "INSERT INTO journal_caving_data (journal_id, template_id) "
                    "VALUES (:jid, :tid)"
                ),
                {"jid": ids["caving"], "tid": _CAVING_TEMPLATE},
            )
            # Every abseiling-derived journal already has an abseiling_data row.
            for jid in ids.values():
                await conn.execute(
                    text(
                        "INSERT INTO journal_abseiling_data (journal_id) VALUES (:jid)"
                    ),
                    {"jid": jid},
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


async def _can_insert_abseiling_template(engine_url: str) -> bool:
    """Return True if an 'abseiling' template passes the type CHECK constraint.

    Rolls back so the probe never persists a row — otherwise a later downgrade
    that re-narrows the CHECK would fail validating against leftover data.
    """
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            try:
                await conn.execute(
                    text(
                        """
                        INSERT INTO activity_templates (user_id, name, template_type)
                        VALUES ('test-user-123', 'Abseil template', 'abseiling')
                        """
                    )
                )
            except IntegrityError:
                return False
            await conn.rollback()
            return True
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestConsolidateTemplateIdMigration:
    """0094 add + backfill journal_abseiling_data.template_id."""

    async def test_upgrade_backfills_and_downgrade_round_trips(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        # 1. At 0093 the column does not exist and 'abseiling' is rejected.
        run_alembic(url, "upgrade", "0093")
        assert not await _column_exists(url, "journal_abseiling_data", "template_id")
        assert not await _can_insert_abseiling_template(url)

        ids = await _seed(url)

        # 2. Upgrade applies the column, CHECK change, and backfill.
        run_alembic(url, "upgrade", "0094")
        assert await _column_exists(url, "journal_abseiling_data", "template_id")
        assert (
            await _abseiling_template_id(url, ids["canyoning"]) == _CANYONING_TEMPLATE
        )
        assert await _abseiling_template_id(url, ids["climbing"]) == _CLIMBING_TEMPLATE
        assert await _abseiling_template_id(url, ids["caving"]) == _CAVING_TEMPLATE
        assert await _can_insert_abseiling_template(url)

        # 3. Idempotent re-run leaves the backfilled values intact.
        run_alembic(url, "upgrade", "0094")
        assert await _abseiling_template_id(url, ids["climbing"]) == _CLIMBING_TEMPLATE

        # 4. Downgrade removes the column and restores the old CHECK; the old
        #    subtype columns retain their values (non-destructive).
        run_alembic(url, "downgrade", "0093")
        assert not await _column_exists(url, "journal_abseiling_data", "template_id")
        assert not await _can_insert_abseiling_template(url)

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                climbing_tid = (
                    await conn.execute(
                        text(
                            "SELECT template_id FROM journal_climbing_data "
                            "WHERE journal_id = :jid"
                        ),
                        {"jid": ids["climbing"]},
                    )
                ).scalar()
            assert str(climbing_tid) == _CLIMBING_TEMPLATE
        finally:
            await engine.dispose()
