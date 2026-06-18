"""Migration round-trip test for 0091 (backfill sync_metadata from external_references).

Verifies the data migration that makes ``sync_metadata`` the complete, current
link store:

- an ``external_references`` row with no paired ``sync_metadata`` is backfilled
  (new rows get ``version_hash = ''`` so the next sync re-validates content);
- the bug shape (a contact with an ``immich`` external_ref but only a ``google``
  ``sync_metadata`` row) ends up with **both** links present;
- duplicate ``external_references`` rows for one ``(source, external_id)`` resolve
  to a single ``sync_metadata`` row (winner = internal id that exists), and the
  losers are logged to ``link_backfill_quarantine`` (no silent data loss);
- album ``reference_data`` is copied intact onto the pre-existing
  ``immich_album`` ``sync_metadata`` row while its ``version_hash`` is preserved;
- the backfill is idempotent (downgrade drops the quarantine table only, and a
  re-run produces the same end state).

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from sqlalchemy import Row, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

_GOOGLE_ONLY_RES = "people/c_google_only"
_BUG_IMMICH_PERSON = "immich-person-bug"
_BUG_GOOGLE_RES = "people/c_bug"
_DUP_PERSON = "immich-person-dup"
_ALBUM_ID = "album-backfill"


async def _insert_contact(conn: AsyncConnection, first: str, last: str) -> int:
    """Insert a contact and return its generated id."""
    row = (
        await conn.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES (:first, :last) RETURNING id"
            ),
            {"first": first, "last": last},
        )
    ).fetchone()
    assert row is not None
    return int(row.id)


async def _seed(engine_url: str) -> dict[str, int]:
    """Seed the bug-shaped link data at the 0089 schema. Returns key ids."""
    engine = create_async_engine(engine_url)
    ids: dict[str, int] = {}
    try:
        async with engine.begin() as conn:
            # A real contact whose id the duplicate winner must point at.
            ids["winner_contact"] = await _insert_contact(conn, "Winner", "Contact")
            ids["bug_contact"] = await _insert_contact(conn, "Bug", "Contact")
            # An internal id that does NOT exist -> the duplicate loser.
            orphan_id = 9_000_001
            ids["orphan"] = orphan_id

            async def _ext_ref(
                ite: str,
                iid: int,
                system: str,
                ete: str,
                eid: str,
                reference_data: str | None = None,
            ) -> None:
                await conn.execute(
                    text("""
                        INSERT INTO external_references
                            (internal_entity_type, internal_entity_id, external_system,
                             external_entity_type, external_entity_id, reference_data,
                             created_at, updated_at)
                        VALUES (:ite, :iid, :system, :ete, :eid, :rd, now(), now())
                    """),
                    {
                        "ite": ite,
                        "iid": iid,
                        "system": system,
                        "ete": ete,
                        "eid": eid,
                        "rd": reference_data,
                    },
                )

            # 1. google external_ref, no sync_metadata -> backfilled.
            await _ext_ref(
                "contact", ids["bug_contact"], "google", "person", _GOOGLE_ONLY_RES
            )
            # 2. bug case: immich external_ref + google sync_metadata only.
            await _ext_ref(
                "contact", ids["bug_contact"], "immich", "person", _BUG_IMMICH_PERSON
            )
            await conn.execute(
                text("""
                    INSERT INTO sync_metadata
                        (internal_id, integration_source, external_id,
                         last_synced_at, version_hash, sync_status)
                    VALUES (:iid, 'google', :eid, now(), 'real-google-hash', 'success')
                """),
                {"iid": ids["bug_contact"], "eid": _BUG_GOOGLE_RES},
            )
            # 3. duplicate immich external_refs -> one wins, one quarantined.
            await _ext_ref(
                "contact", ids["winner_contact"], "immich", "person", _DUP_PERSON
            )
            await _ext_ref("contact", orphan_id, "immich", "person", _DUP_PERSON)
            # 4. album external_ref reference_data + pre-existing immich_album row.
            await _ext_ref(
                "journal",
                900,
                "immich",
                "album",
                _ALBUM_ID,
                reference_data='{"album_name": "Trip", "asset_count": 3}',
            )
            await conn.execute(
                text("""
                    INSERT INTO sync_metadata
                        (internal_id, integration_source, external_id,
                         last_synced_at, version_hash, sync_status,
                         internal_entity_type, external_entity_type)
                    VALUES (900, 'immich_album', :eid, now(), 'album-hash', 'success',
                            'journal', 'album')
                """),
                {"eid": _ALBUM_ID},
            )
    finally:
        await engine.dispose()
    return ids


async def _sync_rows(
    engine_url: str, source: str, external_id: str
) -> Sequence[Row[Any]]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("""
                        SELECT internal_id, version_hash, internal_entity_type,
                               external_entity_type, reference_data, last_synced_at
                        FROM sync_metadata
                        WHERE integration_source = :source AND external_id = :eid
                    """),
                    {"source": source, "eid": external_id},
                )
            ).fetchall()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestBackfillSyncMetadataMigration:
    """0091 backfill from external_references onto sync_metadata."""

    async def test_backfill_then_idempotent_re_run(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)

        run_alembic(url, "upgrade", "0089")
        ids = await _seed(url)
        run_alembic(url, "upgrade", "0091")

        # 1. google-only external_ref backfilled; new row gets version_hash '' and
        #    last_synced_at at the epoch so a pending outbound push is not
        #    suppressed (the push gates on updated_at > last_synced_at).
        google = await _sync_rows(url, "google", _GOOGLE_ONLY_RES)
        assert len(google) == 1
        assert google[0].internal_id == ids["bug_contact"]
        assert google[0].version_hash == ""
        assert google[0].internal_entity_type == "contact"
        assert google[0].external_entity_type == "person"
        assert google[0].last_synced_at.year == 1970

        # 2. bug case: both links present; google row's real hash preserved.
        bug_immich = await _sync_rows(url, "immich", _BUG_IMMICH_PERSON)
        assert len(bug_immich) == 1
        assert bug_immich[0].internal_id == ids["bug_contact"]
        bug_google = await _sync_rows(url, "google", _BUG_GOOGLE_RES)
        assert len(bug_google) == 1
        assert bug_google[0].version_hash == "real-google-hash"

        # 3. duplicate immich refs -> one winning sync_metadata + quarantined loser.
        dup = await _sync_rows(url, "immich", _DUP_PERSON)
        assert len(dup) == 1
        assert dup[0].internal_id == ids["winner_contact"]

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                quarantined = (
                    await conn.execute(
                        text("""
                            SELECT internal_id, integration_source, external_id
                            FROM link_backfill_quarantine
                        """)
                    )
                ).fetchall()
        finally:
            await engine.dispose()
        assert len(quarantined) == 1
        assert quarantined[0].internal_id == ids["orphan"]
        assert quarantined[0].integration_source == "immich"
        assert quarantined[0].external_id == _DUP_PERSON

        # 4. album reference_data copied intact onto the pre-existing row;
        #    version_hash and last_synced_at preserved (not reset to the epoch).
        album = await _sync_rows(url, "immich_album", _ALBUM_ID)
        assert len(album) == 1
        assert album[0].version_hash == "album-hash"
        assert album[0].last_synced_at.year != 1970
        assert album[0].reference_data is not None
        assert json.loads(album[0].reference_data) == {
            "album_name": "Trip",
            "asset_count": 3,
        }

        # 5. idempotency: downgrade drops the quarantine table, re-upgrade is a
        #    no-op (no duplicate sync_metadata rows, single quarantine entry).
        run_alembic(url, "downgrade", "0090")
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                has_quarantine = (
                    await conn.execute(
                        text("SELECT to_regclass('public.link_backfill_quarantine')")
                    )
                ).scalar()
            assert has_quarantine is None
        finally:
            await engine.dispose()

        run_alembic(url, "upgrade", "0091")
        assert len(await _sync_rows(url, "immich", _DUP_PERSON)) == 1
        assert len(await _sync_rows(url, "google", _GOOGLE_ONLY_RES)) == 1

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM link_backfill_quarantine")
                    )
                ).scalar()
            assert count == 1
        finally:
            await engine.dispose()
