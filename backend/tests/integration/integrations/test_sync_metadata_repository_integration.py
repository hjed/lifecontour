"""Integration tests for SyncMetadataRepository link writes.

Verifies that ``upsert`` persists the consolidated link columns
(``internal_entity_type``, ``external_entity_type``, ``reference_data``) to a
real database, that a later writer which omits them does not clobber the
existing values (COALESCE-on-conflict behaviour), and that every link write
stamps its owner and is keyed by ``(user_id, integration_source, external_id)``
— a link another user already holds is refused, not re-pointed.
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    ExternalLinkOwnedByAnotherUserError,
    SyncMetadataRepository,
)
from tests.integration.contact_seeding import TEST_USER_ID

OTHER_USER_ID = "other-user-456"


async def _links(
    connection: AsyncConnection, external_id: str
) -> list[tuple[Any, ...]]:
    rows = await connection.execute(
        text(
            "SELECT id, user_id, internal_id, version_hash FROM sync_metadata "
            "WHERE external_id = :external_id ORDER BY id"
        ),
        {"external_id": external_id},
    )
    return [tuple(row) for row in rows.fetchall()]


@pytest.mark.integration
class TestSyncMetadataRepositoryLinkColumns:
    """upsert persists and preserves the consolidated link columns."""

    async def test_upsert_persists_link_columns(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        result = await repo.upsert(
            user_id=TEST_USER_ID,
            internal_id=101,
            integration_source="google",
            external_id="people/c-link-1",
            version_hash="hash-1",
            internal_entity_type="contact",
            external_entity_type="person",
            reference_data='{"etag": "abc"}',
        )

        assert result.internal_entity_type == "contact"
        assert result.external_entity_type == "person"
        assert result.reference_data == '{"etag": "abc"}'

        row = (
            await clean_database.execute(
                text(
                    "SELECT internal_entity_type, external_entity_type, "
                    "reference_data FROM sync_metadata "
                    "WHERE integration_source = 'google' "
                    "AND external_id = 'people/c-link-1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row.internal_entity_type == "contact"
        assert row.external_entity_type == "person"
        assert row.reference_data == '{"etag": "abc"}'

    async def test_upsert_without_link_columns_preserves_existing(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        await repo.upsert(
            user_id=TEST_USER_ID,
            internal_id=202,
            integration_source="immich",
            external_id="person-link-2",
            version_hash="hash-1",
            internal_entity_type="contact",
            external_entity_type="person",
            reference_data='{"synced_tags": ["a"]}',
        )

        # A later writer (e.g. a worker still on the old code path) omits the
        # link columns; COALESCE must keep the previously-stored values.
        preserved = await repo.upsert(
            user_id=TEST_USER_ID,
            internal_id=202,
            integration_source="immich",
            external_id="person-link-2",
            version_hash="hash-2",
        )

        assert preserved.version_hash == "hash-2"
        assert preserved.internal_entity_type == "contact"
        assert preserved.external_entity_type == "person"
        assert preserved.reference_data == '{"synced_tags": ["a"]}'


@pytest.mark.integration
class TestSyncMetadataRepositoryOwner:
    """Every link write stamps its owner and conflicts on the per-user key."""

    async def test_a_same_owner_resync_updates_the_link_in_place(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        first = await repo.upsert(
            user_id=TEST_USER_ID,
            integration_source="google",
            external_id="people/owned",
            version_hash="hash-1",
            internal_id=301,
        )

        second = await repo.upsert(
            user_id=TEST_USER_ID,
            integration_source="google",
            external_id="people/owned",
            version_hash="hash-2",
            internal_id=301,
        )

        assert second.id == first.id
        assert await _links(clean_database, "people/owned") == [
            (first.id, TEST_USER_ID, 301, "hash-2")
        ]

    async def test_another_owners_link_is_refused_and_left_intact(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        first = await repo.upsert(
            user_id=TEST_USER_ID,
            integration_source="snipeit",
            external_id="asset-7",
            version_hash="hash-1",
            internal_id=401,
        )

        with pytest.raises(ExternalLinkOwnedByAnotherUserError) as refused:
            await repo.upsert(
                user_id=OTHER_USER_ID,
                integration_source="snipeit",
                external_id="asset-7",
                version_hash="hash-2",
                internal_id=402,
            )

        assert refused.value.integration_source == "snipeit"
        assert refused.value.external_id == "asset-7"
        assert OTHER_USER_ID not in str(refused.value)
        # The refusal is contained: the connection still serves the caller.
        assert await _links(clean_database, "asset-7") == [
            (first.id, TEST_USER_ID, 401, "hash-1")
        ]

    async def test_a_contact_link_is_stamped_with_its_owner(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        await repo.upsert_contact_link(
            contact_id=501,
            user_id=TEST_USER_ID,
            external_system="immich",
            external_entity_type="person",
            external_entity_id="person-501",
        )

        [(_, owner, internal_id, _)] = await _links(clean_database, "person-501")
        assert (owner, internal_id) == (TEST_USER_ID, 501)

    async def test_a_journal_link_from_a_merge_is_stamped_with_its_owner(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        created = await repo.link_journal_if_unlinked(
            journal_id=601,
            user_id=TEST_USER_ID,
            integration_source="strava",
            external_id="activity-601",
            external_entity_type="activity",
            transaction=clean_database,
        )
        again = await repo.link_journal_if_unlinked(
            journal_id=602,
            user_id=TEST_USER_ID,
            integration_source="strava",
            external_id="activity-601",
            external_entity_type="activity",
            transaction=clean_database,
        )

        assert (created, again) == (True, False)
        [(_, owner, internal_id, _)] = await _links(clean_database, "activity-601")
        assert (owner, internal_id) == (TEST_USER_ID, 601)

    async def test_a_merge_link_another_owner_holds_is_refused(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await repo.link_journal_if_unlinked(
            journal_id=701,
            user_id=OTHER_USER_ID,
            integration_source="strava",
            external_id="activity-701",
            external_entity_type="activity",
            transaction=clean_database,
        )

        with pytest.raises(ExternalLinkOwnedByAnotherUserError):
            await repo.link_journal_if_unlinked(
                journal_id=702,
                user_id=TEST_USER_ID,
                integration_source="strava",
                external_id="activity-701",
                external_entity_type="activity",
                transaction=clean_database,
            )

        [(_, owner, internal_id, _)] = await _links(clean_database, "activity-701")
        assert (owner, internal_id) == (OTHER_USER_ID, 701)

    async def test_an_unowned_row_is_not_reported_as_another_users(
        self, clean_database: AsyncConnection
    ) -> None:
        """A row with no owner yet (written before its writer stamped one) is
        not another user's: the write fails as it is, to be retried once
        ``0126`` assigns the row, rather than being refused for good."""
        await clean_database.execute(
            text(
                "INSERT INTO sync_metadata (integration_source, external_id, "
                "last_synced_at, version_hash, sync_status) "
                "VALUES ('google', 'people/unowned', now(), 'h', 'success')"
            )
        )
        repo = SyncMetadataRepository(clean_database)

        with pytest.raises(IntegrityError):
            await repo.upsert(
                user_id=TEST_USER_ID,
                integration_source="google",
                external_id="people/unowned",
                version_hash="hash-2",
            )

        [(_, owner, _, version_hash)] = await _links(clean_database, "people/unowned")
        assert (owner, version_hash) == (None, "h")


async def _seed_link(
    repo: SyncMetadataRepository,
    *,
    user_id: str,
    external_id: str,
    internal_id: int,
    integration_source: str = "google",
    internal_entity_type: str = "contact",
) -> None:
    await repo.upsert(
        user_id=user_id,
        integration_source=integration_source,
        external_id=external_id,
        version_hash="hash-1",
        internal_id=internal_id,
        internal_entity_type=internal_entity_type,
        reference_data='{"original": true}',
    )


async def _reference_data(
    connection: AsyncConnection, external_id: str
) -> list[tuple[Any, ...]]:
    rows = await connection.execute(
        text(
            "SELECT user_id, internal_id, reference_data FROM sync_metadata "
            "WHERE external_id = :external_id ORDER BY id"
        ),
        {"external_id": external_id},
    )
    return [tuple(row) for row in rows.fetchall()]


@pytest.mark.integration
class TestSyncMetadataRepositoryOwnerScopedLookups:
    """Lookups, updates and deletes see only the acting owner's links."""

    async def test_a_lookup_for_another_owners_link_finds_nothing(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo, user_id=OTHER_USER_ID, external_id="people/theirs", internal_id=11
        )

        mine = await repo.find_by_external_id(
            "google", "people/theirs", user_id=TEST_USER_ID
        )
        theirs = await repo.find_by_external_id(
            "google", "people/theirs", user_id=OTHER_USER_ID
        )

        assert mine is None
        assert theirs is not None
        assert theirs.internal_id == 11

    async def test_locking_another_owners_link_finds_nothing(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo, user_id=OTHER_USER_ID, external_id="people/locked", internal_id=12
        )

        mine = await repo.find_and_lock("google", "people/locked", user_id=TEST_USER_ID)
        theirs = await repo.find_and_lock(
            "google", "people/locked", user_id=OTHER_USER_ID
        )

        assert mine is None
        assert theirs is not None
        assert theirs.internal_id == 12

    async def test_updating_reference_data_leaves_another_owners_link_alone(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo, user_id=OTHER_USER_ID, external_id="people/ref", internal_id=13
        )

        await repo.update_reference_data(
            "google", "people/ref", '{"synced_tags": []}', user_id=TEST_USER_ID
        )

        assert await _reference_data(clean_database, "people/ref") == [
            (OTHER_USER_ID, 13, '{"original": true}')
        ]

    async def test_a_contact_merge_repoints_only_the_owners_links(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo, user_id=TEST_USER_ID, external_id="people/mine", internal_id=21
        )
        # A link wrongly pointing at the same contact id under another owner.
        await _seed_link(
            repo,
            user_id=OTHER_USER_ID,
            external_id="person-theirs",
            internal_id=21,
            integration_source="immich",
        )

        collisions = await repo.repoint_contact_links(
            21, 22, clean_database, user_id=TEST_USER_ID
        )

        assert collisions == []
        assert await _reference_data(clean_database, "people/mine") == [
            (TEST_USER_ID, 22, '{"original": true}')
        ]
        assert await _reference_data(clean_database, "person-theirs") == [
            (OTHER_USER_ID, 21, '{"original": true}')
        ]

    async def test_a_contact_merge_collision_drops_only_the_owners_link(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo, user_id=TEST_USER_ID, external_id="people/survivor", internal_id=32
        )
        await _seed_link(
            repo, user_id=OTHER_USER_ID, external_id="people/source", internal_id=31
        )

        collisions = await repo.repoint_contact_links(
            31, 32, clean_database, user_id=TEST_USER_ID
        )

        assert collisions == []
        assert await _reference_data(clean_database, "people/source") == [
            (OTHER_USER_ID, 31, '{"original": true}')
        ]

    async def test_a_journal_merge_repoints_only_the_owners_links(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)
        await _seed_link(
            repo,
            user_id=TEST_USER_ID,
            external_id="activity-mine",
            internal_id=41,
            integration_source="strava",
            internal_entity_type="journal",
        )
        await _seed_link(
            repo,
            user_id=OTHER_USER_ID,
            external_id="album-theirs",
            internal_id=41,
            integration_source="immich_album",
            internal_entity_type="journal",
        )
        # The target holds a strava link of its own under another owner, which
        # must not count as a collision for the acting owner's merge.
        await _seed_link(
            repo,
            user_id=OTHER_USER_ID,
            external_id="activity-theirs",
            internal_id=42,
            integration_source="strava",
            internal_entity_type="journal",
        )

        collisions = await repo.repoint_journal_links(
            41, 42, clean_database, user_id=TEST_USER_ID
        )

        assert collisions == []
        assert await _reference_data(clean_database, "activity-mine") == [
            (TEST_USER_ID, 42, '{"original": true}')
        ]
        assert await _reference_data(clean_database, "album-theirs") == [
            (OTHER_USER_ID, 41, '{"original": true}')
        ]
