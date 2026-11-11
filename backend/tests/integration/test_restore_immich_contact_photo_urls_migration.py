"""Migration test for 0144 (restore the Immich avatar of linked contacts).

Before inbound syncs were scoped to the fields their source owns, every Google
update wrote ``photo_url = NULL`` over the Immich avatar, and the Immich pull
skips a person it has not seen change, so the avatar never came back. 0144
gives every contact its owner linked to an Immich person the avatar URL again.

Runs against an isolated throwaway database.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.integration.contact_seeding import seed_contact
from tests.integration.migration_helpers import RunAlembic

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "11111111-2222-4333-8444-555555555555"
# A fixed past instant: the migration's ``now()`` can never equal it.
SEEDED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


async def _insert_contact(
    conn: AsyncConnection, name: str, *, photo_url: str | None = None
) -> int:
    return await seed_contact(
        conn,
        user_id=OWNER,
        first_name=name,
        photo_url=photo_url,
        created_at=SEEDED_AT,
        updated_at=SEEDED_AT,
    )


async def _link(
    conn: AsyncConnection, contact_id: int, *, source: str, owner: str = OWNER
) -> None:
    external_id = f"{source}-person-{contact_id}"
    await conn.execute(
        text("""
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, internal_entity_type,
                external_entity_type
            ) VALUES (
                :owner, :cid, :source, :eid, now(), 'hash', 'success', 'contact',
                'person'
            )
        """),
        {"owner": owner, "cid": contact_id, "source": source, "eid": external_id},
    )


async def _contacts(url: str) -> dict[str, tuple[str | None, datetime]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT first_name, photo_url, updated_at FROM contacts")
            )
            return {row.first_name: (row.photo_url, row.updated_at) for row in rows}
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestRestoreImmichContactPhotoUrls:
    """0144 restores the avatar URL of every owner-linked Immich contact."""

    async def test_restores_only_owner_linked_immich_contacts_without_a_photo(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0143")

        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                cleared = await _insert_contact(conn, "cleared")
                await _link(conn, cleared, source="immich")
                await _link(conn, cleared, source="google")

                with_photo = await _insert_contact(
                    conn, "with_photo", photo_url="https://example.test/me.jpg"
                )
                await _link(conn, with_photo, source="immich")

                await _insert_contact(conn, "unlinked")

                google_only = await _insert_contact(conn, "google_only")
                await _link(conn, google_only, source="google")

                foreign_link = await _insert_contact(conn, "foreign_link")
                await _link(conn, foreign_link, source="immich", owner=OTHER_OWNER)
        finally:
            await engine.dispose()

        run_alembic(url, "upgrade", "0144")

        assert await _contacts(url) == {
            "cleared": (f"/api/contacts/{cleared}/avatar", SEEDED_AT),
            "with_photo": ("https://example.test/me.jpg", SEEDED_AT),
            "unlinked": (None, SEEDED_AT),
            "google_only": (None, SEEDED_AT),
            "foreign_link": (None, SEEDED_AT),
        }

    async def test_downgrade_keeps_the_restored_photo(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0143")
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                cleared = await _insert_contact(conn, "cleared")
                await _link(conn, cleared, source="immich")
        finally:
            await engine.dispose()
        run_alembic(url, "upgrade", "0144")

        run_alembic(url, "downgrade", "0143")

        assert await _contacts(url) == {
            "cleared": (f"/api/contacts/{cleared}/avatar", SEEDED_AT)
        }
